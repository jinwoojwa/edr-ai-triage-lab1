"""🔍 조사 도구: 에이전트가 PC 기록을 조사할 때 부르는 함수들.

도구 계약 (docs/CONTRACT.md)
- 모든 결과의 기록 하나하나에 `event_id`가 있다 → 가드레일이 판정 근거를 검증하는 데 씀
- 명령줄은 앞부분만 (요약) → LLM에게 넘기는 글자 수가 곧 비용과 속도

함수의 설명(docstring)은 LLM이 '어떤 도구를 부를지' 고를 때 읽는 글입니다. 신경 써서 쓰세요.

    pytest tests/test_telemetry_tools.py -q
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from ipaddress import ip_address, ip_network
from statistics import fmean, pstdev

from langchain_core.tools import tool

from ..config import settings
from ..osclient import get_client

EVENTS = f"{settings.index_events}-*"
CMD_MAX = 120           # 명령줄 요약 길이
MAX_ANCESTORS = 5
MAX_CHILDREN = 20
ACTIVITY_LIMIT = 50
TIMELINE_LIMIT = 100
NETWORK_LIMIT = 1000
NETWORK_DESTINATIONS = 20
NETWORK_EVIDENCE = 5
INTERNAL_NETWORKS = tuple(ip_network(cidr) for cidr in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7",
))


def _search(body: dict) -> list[dict]:
    res = get_client().search(index=EVENTS, body=body)
    return [h["_source"] for h in res["hits"]["hits"]]


def summarize(e: dict) -> dict:
    """기록 하나를 LLM에게 넘길 모양으로 줄입니다. (이미 만들어 둔 도우미)"""
    p = e.get("process", {})
    out = {"event_id": e["event_id"], "ts": e["ts"], "type": e["type"],
           "pid": p.get("pid"), "ppid": p.get("ppid"), "name": p.get("name"),
           "cmdline": (p.get("cmdline") or "")[:CMD_MAX], "user": p.get("user"), "signed": p.get("signed")}
    if e.get("network"):
        n = e["network"]
        out["detail"] = f"{n['dst_ip']}:{n['dst_port']} ({n.get('bytes_out', 0)} bytes)"
    elif e.get("file"):
        f = e["file"]
        out["detail"] = f"{f['action']} {f['path']}" + (f" → {f['new_path']}" if f.get("new_path") else "")
    elif e.get("registry"):
        out["detail"] = f"{e['registry']['key']} = {e['registry']['value']}"
    elif e.get("script_text"):
        out["detail"] = e["script_text"][:200]
    return out


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------- 입력 검증 (docs/CONTRACT.md)
# 잘못된 입력은 ValueError. 에이전트의 도구 실행 노드가 예외를 잡아 LLM에게 오류로 알려 줍니다.
def _check_host(host) -> str:
    if not isinstance(host, str) or not host.strip():
        raise ValueError("host는 비어 있지 않은 문자열이어야 합니다 (예: WS-007)")
    return host


def _check_pid(pid) -> int:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid < 0:
        raise ValueError("pid는 0 이상의 정수여야 합니다")
    return pid


def _check_minutes(minutes) -> int:
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes <= 0:
        raise ValueError("minutes는 0보다 큰 정수여야 합니다")
    return minutes


def _check_around_ts(around_ts, name: str = "around_ts") -> datetime:
    """시간대가 있는 ISO 8601 문자열만 받아 UTC로 바꿉니다. 시간대가 없으면 기준 시각이 모호해서 거절합니다."""
    if not isinstance(around_ts, str):
        raise ValueError(f"{name}는 ISO 8601 문자열이어야 합니다 (예: 2026-11-16T09:12:02Z)")
    try:
        t = _parse_ts(around_ts)
    except ValueError:
        raise ValueError(f"{name}를 시각으로 읽을 수 없습니다: {around_ts!r} (예: 2026-11-16T09:12:02Z)") from None
    if t.tzinfo is None:
        raise ValueError(f"{name}에 시간대가 없습니다. Z 또는 +09:00 같은 시간대를 붙이세요")
    return t.astimezone(timezone.utc)


def _find_process(host: str, pid: int) -> dict | None:
    """host에서 pid를 가진 '프로세스 생성' 기록 하나."""
    rows = _search({"size": 1, "sort": [{"ts": "desc"}], "query": {"bool": {"filter": [
        {"term": {"host": host}}, {"term": {"type": "process"}}, {"term": {"process.pid": pid}}]}}})
    return rows[0] if rows else None


def get_process_tree(host: str, pid: int) -> dict:
    """프로세스의 족보를 봅니다: 누가 이 프로세스를 실행했는지(부모, 조부모 …)와 이 프로세스가 실행한 자식들.
    '누가 실행했나', '정상 프로그램이 띄운 것인가'를 확인할 때 씁니다.

    Args:
        host: PC 이름 (예: WS-007)
        pid: 프로세스 번호 (알림의 pid)
    """
    host, pid = _check_host(host), _check_pid(pid)
    proc = _find_process(host, pid)
    if proc is None:
        return {"host": host, "pid": pid, "process": None, "ancestors": [], "children": []}

    # 부모 거슬러 올라가기: 같은 host에서, 자식보다 '이전' 시각에 생성된 프로세스만 부모로 봅니다.
    # (pid는 재사용되므로 시각 조건이 없으면 나중에 같은 번호를 쓴 다른 프로세스가 섞입니다.)
    ancestors: list[dict] = []
    note = None
    seen = {pid}
    cur = proc
    for _ in range(MAX_ANCESTORS):
        p = cur["process"]
        ppid = p.get("ppid")
        if ppid is None or ppid in seen:       # 부모가 없거나 순환
            break
        rows = _search({"size": 1, "sort": [{"ts": "desc"}, {"event_id": "desc"}], "query": {"bool": {"filter": [
            {"term": {"host": host}}, {"term": {"type": "process"}}, {"term": {"process.pid": ppid}},
            {"range": {"ts": {"lte": cur["ts"]}}}]}}})
        if not rows:
            who = f", {p['parent_name']}" if p.get("parent_name") else ""
            note = f"부모 프로세스(pid {ppid}{who})의 생성 기록이 없습니다."
            break
        cur = rows[0]
        seen.add(ppid)
        ancestors.append(summarize(cur))

    # 자식: 이 프로세스가 시작된 뒤에 같은 host에서 ppid가 pid인 프로세스 (ts 오름차순, 같으면 event_id)
    kids = _search({"size": MAX_CHILDREN, "sort": [{"ts": "asc"}, {"event_id": "asc"}], "query": {"bool": {
        "filter": [{"term": {"host": host}}, {"term": {"type": "process"}}, {"term": {"process.ppid": pid}},
                   {"range": {"ts": {"gte": proc["ts"]}}}],
        "must_not": [{"term": {"event_id": proc["event_id"]}}]}}})

    out = {"host": host, "pid": pid, "process": summarize(proc), "ancestors": ancestors,
           "children": [summarize(k) for k in kids]}
    if note:
        out["note"] = note
    return out


def get_process_activity(host: str, pid: int) -> dict:
    """한 프로세스가 한 일을 시간순으로 봅니다: 네트워크 연결, 파일 생성·변경, 레지스트리 변경, 실행한 스크립트.
    '이 프로세스가 무엇을 남겼나(파일, 통신)'를 확인할 때 씁니다.

    Args:
        host: PC 이름 (예: WS-007)
        pid: 프로세스 번호
    """
    host, pid = _check_host(host), _check_pid(pid)
    # 가장 최근 50건을 고른 뒤 시간순(오름차순)으로 돌려줍니다. 프로세스 생성 기록(process)은 get_process_tree의 몫입니다.
    rows = _search({"size": ACTIVITY_LIMIT, "sort": [{"ts": "desc"}, {"event_id": "desc"}], "query": {"bool": {
        "filter": [{"term": {"host": host}}, {"term": {"process.pid": pid}},
                   {"terms": {"type": ["network", "file", "registry", "script"]}}]}}})
    return {"host": host, "pid": pid, "events": [summarize(e) for e in reversed(rows)]}


def get_host_timeline(host: str, around_ts: str, minutes: int = 10) -> dict:
    """특정 시각 앞뒤로 그 PC에서 일어난 모든 일을 시간순으로 봅니다.
    알림 직전·직후에 다른 수상한 활동(다른 프로그램, 다른 통신)이 있었는지 넓게 볼 때 씁니다.

    Args:
        host: PC 이름 (예: WS-007)
        around_ts: 기준 시각 (ISO 형식, 예: 2026-11-16T09:12:02Z). 보통 알림 시각
        minutes: 기준 시각 앞뒤로 몇 분까지 볼지 (기본 10)
    """
    host, minutes, t = _check_host(host), _check_minutes(minutes), _check_around_ts(around_ts)
    try:
        start, end = t - timedelta(minutes=minutes), t + timedelta(minutes=minutes)
    except OverflowError:
        raise ValueError("minutes가 너무 큽니다") from None
    # 한 건 더 요청해서(LIMIT + 1) 잘렸는지 압니다. 범위의 양 끝은 포함합니다.
    rows = _search({"size": TIMELINE_LIMIT + 1, "sort": [{"ts": "asc"}, {"event_id": "asc"}], "query": {"bool": {
        "filter": [{"term": {"host": host}}, {"range": {"ts": {"gte": _iso(start), "lte": _iso(end)}}}]}}})
    return {"host": host, "from": _iso(start), "to": _iso(end),
            "events": [summarize(e) for e in rows[:TIMELINE_LIMIT]], "truncated": len(rows) > TIMELINE_LIMIT}




def _external_ip(value: str) -> bool:
    """실습용 문서 IP도 외부로 센다. is_global은 해당 주소를 제외하므로 쓰지 않는다."""
    try:
        address = ip_address(value)
    except ValueError:
        return False
    return not (address.is_loopback or address.is_link_local or address.is_multicast
                or address.is_unspecified or any(address in net for net in INTERNAL_NETWORKS))


def get_network_connections(host: str, minutes: int, until_ts: str | None = None) -> dict:
    """호스트의 외부 IP 통신을 목적지별 횟수와 접속 간격 통계로 요약합니다.

    주기적인 외부 통신이나 비컨이 의심될 때 이 도구를 선택하세요. 목적지(dst_ip)마다 횟수,
    평균·최소·최대 접속 간격(초), 간격의 표준편차를 돌려줍니다. 간격이 일정해서 표준편차가
    작고 최소·최대가 평균에 가까우면 규칙적인(비컨 의심) 통신이고, 표준편차가 평균만큼 크면
    불규칙한 일반 통신입니다. 실제 event_id가 든 최근 기록도 돌려줍니다.

    기본은 현재 UTC 시각부터 직전 minutes분을 봅니다. 오래된 알림이면 until_ts에 알림 시각
    (또는 그보다 조금 뒤)을 넘겨 그 시각까지의 minutes분을 조사하세요. 빈 결과는 '통신 없음'이
    아니라 조회 구간에 기록이 없다는 뜻일 수 있으니, 돌려준 from/to가 알림 시각을 포함하는지
    확인하세요. 내부망 통신이나 특정 프로세스의 상세 활동은 다른 조사 도구로 확인하세요.

    Args:
        host: 조사할 PC 이름 (예: WS-007)
        minutes: until_ts(생략하면 현재 시각)부터 거슬러 볼 분 수 (0보다 큰 정수)
        until_ts: 조회 구간의 끝 시각 (시간대가 있는 ISO 형식, 예: 2026-11-16T09:12:02Z). 생략하면 현재 시각
    """
    host, minutes = _check_host(host), _check_minutes(minutes)
    end = datetime.now(timezone.utc) if until_ts is None else _check_around_ts(until_ts, "until_ts")
    try:
        start = end - timedelta(minutes=minutes)
    except OverflowError:
        raise ValueError("minutes가 너무 큽니다") from None

    # 최근 1,000건만 집계한다. 한 건을 더 받아 결과가 잘렸는지 확인한다.
    rows = _search({"size": NETWORK_LIMIT + 1,
                    "sort": [{"ts": "desc"}, {"event_id": "desc"}],
                    "query": {"bool": {"filter": [
                        {"term": {"host": host}}, {"term": {"type": "network"}},
                        {"range": {"ts": {"gte": _iso(start), "lte": _iso(end)}}},
                    ]}}})
    event_limit_hit = len(rows) > NETWORK_LIMIT
    groups: dict[str, list[dict]] = {}
    for event in rows[:NETWORK_LIMIT]:
        ip = (event.get("network") or {}).get("dst_ip")
        if ip and _external_ip(ip):
            groups.setdefault(ip, []).append(event)

    connections = []
    for ip, events in groups.items():
        events.sort(key=lambda e: (_parse_ts(e["ts"]), e["event_id"]))
        times = [_parse_ts(e["ts"]) for e in events]
        gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:])]     # 연속 연결 사이의 간격(초)
        # 한 건뿐이면 간격이 없으므로 통계는 모두 None. 평균만으로는 규칙적인 비컨과 불규칙한 정상 통신을
        # 구분할 수 없어서, 간격의 최소·최대·표준편차를 함께 돌려준다 (CONTRACT.md).
        stats = ({"avg_interval_seconds": round(fmean(gaps), 2), "min_interval_seconds": round(min(gaps), 2),
                  "max_interval_seconds": round(max(gaps), 2), "interval_stddev_seconds": round(pstdev(gaps), 2)}
                 if gaps else dict.fromkeys(("avg_interval_seconds", "min_interval_seconds",
                                             "max_interval_seconds", "interval_stddev_seconds")))
        connections.append({
            "dst_ip": ip, "count": len(events),
            "first_ts": events[0]["ts"], "last_ts": events[-1]["ts"],
            **stats,
            "events": [summarize(e) for e in events[-NETWORK_EVIDENCE:]],
            "events_truncated": len(events) > NETWORK_EVIDENCE,
        })
    connections.sort(key=lambda x: (-x["count"], x["dst_ip"]))
    return {"host": host, "from": _iso(start), "to": _iso(end),
            "connections": connections[:NETWORK_DESTINATIONS],
            "truncated": event_limit_hit or len(connections) > NETWORK_DESTINATIONS}


TELEMETRY_TOOLS = [tool(get_process_tree), tool(get_process_activity), tool(get_host_timeline),
                   tool(get_network_connections)]
