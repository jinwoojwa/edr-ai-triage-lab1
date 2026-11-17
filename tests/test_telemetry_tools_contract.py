"""🔍 조사 도구 계약 테스트 (docs/CONTRACT.md의 입력 검증, 결과 없음, 개수 제한, 순서).

    pytest tests/test_telemetry_tools_contract.py -q

제공된 test_telemetry_tools.py는 WS-007 이야기와 호스트 혼합 방지를 확인합니다.
여기서는 계약에 적힌 나머지 규칙을 직접 만든 기록으로 확인합니다.
기록은 호스트 이름을 따로 써서(WS-T1 ~ WS-T6) 다른 테스트의 기록과 섞이지 않습니다.
"""
from datetime import datetime, timedelta, timezone

import pytest

from soc.config import settings
from soc.osclient import get_client
from soc.telemetry import tools
from soc.telemetry.index_template import apply_template, index_events

T0 = datetime(2026, 11, 16, 10, 0, 0, tzinfo=timezone.utc)


def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def proc(eid, host, pid, ppid, name, t, parent_name=None):
    p = {"pid": pid, "name": name, "cmdline": name, "signed": True, "user": "t"}
    if ppid is not None:
        p["ppid"] = ppid
    if parent_name:
        p["parent_name"] = parent_name
    return {"event_id": eid, "ts": _iso(t), "host": host, "type": "process", "process": p}


def file_ev(eid, host, pid, t, path="C:\\Temp\\x.tmp"):
    return {"event_id": eid, "ts": _iso(t), "host": host, "type": "file",
            "process": {"pid": pid, "ppid": 1, "name": "x.exe", "cmdline": "x.exe", "signed": True, "user": "t"},
            "file": {"path": path, "action": "create"}}


def _build() -> list[dict]:
    ev: list[dict] = []
    # WS-T1: 부모 8단계 사슬 (pid 1001 → 1002 → … → 1008). 가장 깊은 프로세스는 pid 1008
    for i in range(8):
        pid = 1001 + i
        ppid = pid - 1 if i > 0 else 900
        ev.append(proc(f"t1-{i}", "WS-T1", pid, ppid, f"p{pid}.exe", T0 + timedelta(seconds=i)))
    # WS-T2: 부모 pid 2000에 자식 25개 (생성 시각 오름차순). 첫 자식이 가장 이르다
    ev.append(proc("t2-parent", "WS-T2", 2000, 1, "parent.exe", T0))
    for i in range(25):
        ev.append(proc(f"t2-kid-{i:02d}", "WS-T2", 3000 + i, 2000, f"kid{i}.exe", T0 + timedelta(seconds=i + 1)))
    # WS-T3: pid 4000의 프로세스 생성 기록 1건 + 파일 기록 60건 (시각 오름차순으로 f-00 … f-59)
    ev.append(proc("t3-proc", "WS-T3", 4000, 1, "act.exe", T0))
    for i in range(60):
        ev.append(file_ev(f"t3-f-{i:02d}", "WS-T3", 4000, T0 + timedelta(seconds=i + 1)))
    # WS-T4: 기준 시각 T0 ±1분 안에 정확히 100건, 그 밖(61초 뒤)에 1건
    for i in range(100):
        ev.append(file_ev(f"t4-in-{i:03d}", "WS-T4", 5000, T0 - timedelta(seconds=60) + timedelta(seconds=i * 1.2)))
    ev.append(file_ev("t4-out", "WS-T4", 5000, T0 + timedelta(seconds=61)))
    # WS-T5: pid 재사용. pid 6000이 두 번 쓰였고(old.exe, 나중에 new.exe), 자식 6100은 둘 사이에 만들어짐
    ev.append(proc("t5-old", "WS-T5", 6000, 1, "old.exe", T0))
    ev.append(proc("t5-child", "WS-T5", 6100, 6000, "child.exe", T0 + timedelta(seconds=10)))
    ev.append(proc("t5-new", "WS-T5", 6000, 1, "new.exe", T0 + timedelta(seconds=20)))
    # WS-T6: 순환(7000 ↔ 7001), 부모 없음(ppid 없음), 부모 기록 없음(ppid 7200)
    ev.append(proc("t6-a", "WS-T6", 7000, 7001, "a.exe", T0))
    ev.append(proc("t6-b", "WS-T6", 7001, 7000, "b.exe", T0))
    ev.append(proc("t6-root", "WS-T6", 7100, None, "root.exe", T0))
    ev.append(proc("t6-orphan", "WS-T6", 7300, 7200, "orphan.exe", T0, parent_name="explorer.exe"))
    return ev


@pytest.fixture(scope="module", autouse=True)
def loaded():
    client = get_client()
    client.indices.delete(index=f"{settings.index_events}-*", ignore_unavailable=True)
    apply_template(client)
    index_events(_build(), client)
    yield


def _ids(rows):
    return [r["event_id"] for r in rows]


# ---------------------------------------------------------------------------- 입력 검증
@pytest.mark.parametrize("host", ["", "   ", None, 7])
def test_bad_host_raises(host):
    for call in (lambda: tools.get_process_tree(host, 1), lambda: tools.get_process_activity(host, 1),
                 lambda: tools.get_host_timeline(host, "2026-11-16T10:00:00Z", 5)):
        with pytest.raises(ValueError):
            call()


@pytest.mark.parametrize("pid", [-1, "123", 1.5, None, True])
def test_bad_pid_raises(pid):
    with pytest.raises(ValueError):
        tools.get_process_tree("WS-T1", pid)
    with pytest.raises(ValueError):
        tools.get_process_activity("WS-T1", pid)


def test_pid_zero_is_allowed():
    assert tools.get_process_tree("WS-T1", 0)["process"] is None


@pytest.mark.parametrize("minutes", [0, -5, "10", 1.5, None, True])
def test_bad_minutes_raises(minutes):
    with pytest.raises(ValueError):
        tools.get_host_timeline("WS-T1", "2026-11-16T10:00:00Z", minutes)


@pytest.mark.parametrize("ts", ["abc", "", "2026-11-16T10:00:00", "2026-11-16 10:00:00", None, 123])
def test_bad_around_ts_raises(ts):
    with pytest.raises(ValueError):
        tools.get_host_timeline("WS-T1", ts, 5)


def test_huge_minutes_raises_value_error():
    with pytest.raises(ValueError):
        tools.get_host_timeline("WS-T1", "2026-11-16T10:00:00Z", 10**12)


# ---------------------------------------------------------------------------- 결과 없음
def test_empty_results():
    assert tools.get_process_tree("WS-T1", 99999) == {
        "host": "WS-T1", "pid": 99999, "process": None, "ancestors": [], "children": []}
    assert tools.get_process_activity("WS-T1", 99999) == {"host": "WS-T1", "pid": 99999, "events": []}
    r = tools.get_host_timeline("WS-NONE", "2026-11-16T10:00:00Z", 2)
    assert r == {"host": "WS-NONE", "from": "2026-11-16T09:58:00Z", "to": "2026-11-16T10:02:00Z",
                 "events": [], "truncated": False}


# ---------------------------------------------------------------------------- get_process_tree
def test_ancestors_limited_to_five_nearest_first():
    r = tools.get_process_tree("WS-T1", 1008)
    assert _ids(r["ancestors"]) == ["t1-6", "t1-5", "t1-4", "t1-3", "t1-2"]   # pid 1007 → 1003
    assert [a["pid"] for a in r["ancestors"]] == [1007, 1006, 1005, 1004, 1003]


def test_children_limited_to_twenty_in_time_order():
    r = tools.get_process_tree("WS-T2", 2000)
    assert _ids(r["children"]) == [f"t2-kid-{i:02d}" for i in range(20)]


def test_pid_reuse_picks_parent_created_before_child():
    r = tools.get_process_tree("WS-T5", 6100)
    assert _ids(r["ancestors"]) == ["t5-old"]            # 나중에 같은 번호를 쓴 new.exe가 아님
    assert r["ancestors"][0]["name"] == "old.exe"


def test_children_must_start_after_process():
    # 6000의 가장 최근 기록은 new.exe(+20초). 자식 6100은 +10초에 만들어졌으니 new.exe의 자식이 아니다.
    r = tools.get_process_tree("WS-T5", 6000)
    assert r["process"]["name"] == "new.exe"
    assert r["children"] == []


def test_cycle_does_not_loop():
    r = tools.get_process_tree("WS-T6", 7000)
    assert _ids(r["ancestors"]) == ["t6-b"]               # b의 부모는 a(7000)인데 이미 본 pid라 멈춤


def test_note_only_when_parent_record_missing():
    assert "note" not in tools.get_process_tree("WS-T6", 7100)        # 부모가 없는 프로세스
    r = tools.get_process_tree("WS-T6", 7300)                          # 부모 기록이 없음
    assert r["ancestors"] == []
    assert "7200" in r["note"] and "explorer.exe" in r["note"]


def test_tree_records_have_no_host_field():
    r = tools.get_process_tree("WS-T1", 1003)
    for row in [r["process"], *r["ancestors"], *r["children"]]:
        assert "host" not in row and row["event_id"]


# ---------------------------------------------------------------------------- get_process_activity
def test_activity_latest_50_in_time_order_without_process_records():
    r = tools.get_process_activity("WS-T3", 4000)
    assert len(r["events"]) == 50
    assert _ids(r["events"]) == [f"t3-f-{i:02d}" for i in range(10, 60)]   # 가장 최근 50건, 오름차순
    assert all(e["type"] != "process" for e in r["events"])


# ---------------------------------------------------------------------------- get_host_timeline
def test_timeline_exactly_limit_is_not_truncated():
    r = tools.get_host_timeline("WS-T4", _iso(T0), 1)
    assert len(r["events"]) == 100
    assert r["truncated"] is False
    assert "t4-out" not in _ids(r["events"])                           # 61초 뒤는 범위 밖
    assert r["from"] == "2026-11-16T09:59:00Z" and r["to"] == "2026-11-16T10:01:00Z"
    ts = [e["ts"] for e in r["events"]]
    assert ts == sorted(ts)


def test_timeline_truncated_when_over_limit():
    r = tools.get_host_timeline("WS-T4", _iso(T0), 2)                           # ±2분이면 101건이 모두 들어옴
    assert len(r["events"]) == 100
    assert r["truncated"] is True
    assert _ids(r["events"])[0] == "t4-in-000"                          # 앞에서부터 100건


def test_timeline_range_includes_both_ends():
    r = tools.get_host_timeline("WS-T3", _iso(T0 + timedelta(seconds=31)), 1)  # 09:00:31 ±1분 = 09:59:31..10:01:31
    assert "t3-proc" in _ids(r["events"]) and "t3-f-59" in _ids(r["events"])
    r2 = tools.get_host_timeline("WS-T3", _iso(T0), 1)                  # T0가 정확히 기준 시각
    assert "t3-proc" in _ids(r2["events"])


def test_timeline_converts_timezone_to_utc():
    r = tools.get_host_timeline("WS-T3", "2026-11-16T19:00:00+09:00", 1)     # = 10:00:00Z
    assert r["from"] == "2026-11-16T09:59:00Z" and r["to"] == "2026-11-16T10:01:00Z"
    assert "t3-proc" in _ids(r["events"])
