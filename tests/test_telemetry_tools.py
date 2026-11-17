"""🔍 조사 도구 테스트 (TODO[REC-1] ~ [REC-4]).

    pytest tests/test_telemetry_tools.py -q

샘플 기록(data/telemetry/sample_events.jsonl)의 WS-007 이야기를 씁니다 (01 문서의 예시 알림).
  cmd.exe(pid 19329, evt-…22) → rundll32.exe(pid 40702, evt-…23) → C:\\Windows\\Temp\\d.dmp 생성(evt-…24)
"""
import copy

import pytest

from soc.config import ROOT, settings
from soc.osclient import get_client
from soc.telemetry import tools
from soc.telemetry.index_template import apply_template, index_events, load_jsonl

SAMPLE = ROOT / "data" / "telemetry" / "sample_events.jsonl"


@pytest.fixture(scope="module", autouse=True)
def loaded():
    client = get_client()
    client.indices.delete(index=f"{settings.index_events}-*", ignore_unavailable=True)
    apply_template(client)
    events = load_jsonl(SAMPLE)
    # 함정: 다른 PC(WS-099)에 같은 pid 40702가 있습니다. host 조건을 빼먹으면 섞입니다.
    twin = copy.deepcopy(next(e for e in events if e["event_id"] == "evt-00000023"))
    twin.update(event_id="evt-twin-0001", host="WS-099")
    twin["process"].update(name="notepad.exe", cmdline="notepad.exe", ppid=1234, parent_name="explorer.exe")
    try:
        index_events(events + [twin], client)
    except Exception as e:  # noqa: BLE001  진짜 OpenSearch: 템플릿이 strict라 매핑에 없는 칸이 오면 기록이 거절됨
        first = (getattr(e, "errors", None) or [{}])[0]
        reason = next(iter(first.values()), {}).get("error", {}).get("reason", str(e)[:200])
        pytest.fail(f"TODO[REC-1]: 템플릿 매핑에 없는 칸이 있어 OpenSearch가 기록을 거절했습니다 (dynamic: strict). "
                    f"{len(getattr(e, 'errors', []) or [])}건 실패, 첫 이유: {reason}", pytrace=False)
    yield


def _ids(rows):
    return [r["event_id"] for r in rows]


def test_process_tree_parent_and_note():
    r = tools.get_process_tree("WS-007", 40702)
    assert r["process"]["event_id"] == "evt-00000023"
    assert r["process"]["name"] == "rundll32.exe"
    assert _ids(r["ancestors"]) == ["evt-00000022"]          # 바로 위 부모: cmd.exe
    assert r["children"] == []


def test_process_tree_does_not_mix_hosts():
    r = tools.get_process_tree("WS-099", 40702)
    assert r["process"]["event_id"] == "evt-twin-0001"
    assert "evt-00000022" not in _ids(r["ancestors"])         # WS-007의 cmd.exe가 섞이면 안 됨


def test_process_tree_children():
    r = tools.get_process_tree("WS-007", 19329)                # cmd.exe의 자식 = rundll32.exe
    assert _ids(r["children"]) == ["evt-00000023"]


def test_process_activity_finds_dump_file():
    r = tools.get_process_activity("WS-007", 40702)
    assert _ids(r["events"]) == ["evt-00000024"]
    assert "d.dmp" in r["events"][0]["detail"]


def test_host_timeline_window():
    narrow = tools.get_host_timeline("WS-007", "2026-11-16T09:12:02Z", minutes=1)
    assert _ids(narrow["events"]) == ["evt-00000022", "evt-00000023", "evt-00000024"]
    wide = tools.get_host_timeline("WS-007", "2026-11-16T09:12:02Z", minutes=5)
    assert "evt-00000017" in _ids(wide["events"])               # 09:14:01의 outlook.exe
    assert wide["truncated"] is False


def test_results_are_summarized_with_event_id():
    r = tools.get_host_timeline("WS-002", "2026-11-16T09:05:00Z", minutes=10)
    assert r["events"], "WS-002의 기록이 하나도 없습니다"
    for e in r["events"]:
        assert e["event_id"]
        assert len(e["cmdline"]) <= tools.CMD_MAX


def test_tools_have_docstrings():
    for t in tools.TELEMETRY_TOOLS:
        assert t.description and len(t.description) > 30, f"{t.name}의 설명(docstring)이 너무 짧습니다"


@pytest.mark.skipif(settings.backend != "real", reason="매핑은 진짜 OpenSearch에서만 확인할 수 있습니다")
def test_mapping_types():
    m = get_client().indices.get_mapping(index=f"{settings.index_events}-*")
    props = next(iter(m.values()))["mappings"]["properties"]
    assert props["host"]["type"] == "keyword"
    assert props["ts"]["type"] == "date"
    assert props["process"]["properties"]["pid"]["type"] == "long"
    assert props["process"]["properties"]["cmdline"]["type"] == "text"
    assert "keyword" in props["process"]["properties"]["cmdline"]["fields"]
