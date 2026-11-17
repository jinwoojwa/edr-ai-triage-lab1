"""🔍 조사 도구: 에이전트가 PC 기록을 조사할 때 부르는 함수들.

도구 계약 (docs/CONTRACT.md)
- 모든 결과의 기록 하나하나에 `event_id`가 있다 → 가드레일이 판정 근거를 검증하는 데 씀
- 명령줄은 앞부분만 (요약) → LLM에게 넘기는 글자 수가 곧 비용과 속도

함수의 설명(docstring)은 LLM이 '어떤 도구를 부를지' 고를 때 읽는 글입니다. 신경 써서 쓰세요.

    pytest tests/test_telemetry_tools.py -q
"""
from __future__ import annotations

from datetime import datetime, timedelta

from langchain_core.tools import tool

from ..config import settings
from ..osclient import get_client

EVENTS = f"{settings.index_events}-*"
CMD_MAX = 120           # 명령줄 요약 길이
MAX_ANCESTORS = 5
TIMELINE_LIMIT = 100


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
    # TODO[REC-2]: 부모를 최대 MAX_ANCESTORS단계까지 거슬러 올라가고, 자식(ppid == pid)도 찾습니다.
    # 반드시 host까지 같이 조건에 넣으세요. 다른 PC에 같은 pid가 있을 수 있습니다. (02 문서 9-2 고장 예상표)
    # 돌려줄 모양: {"host", "pid", "process": 요약 또는 None, "ancestors": [가까운 부모부터 요약], "children": [요약]}
    # 요약은 summarize()를 쓰고, 프로세스 기록을 찾을 때는 _find_process()를 쓰면 됩니다.
    raise NotImplementedError("TODO[REC-2]")


def get_process_activity(host: str, pid: int) -> dict:
    """한 프로세스가 한 일을 시간순으로 봅니다: 네트워크 연결, 파일 생성·변경, 레지스트리 변경, 실행한 스크립트.
    '이 프로세스가 무엇을 남겼나(파일, 통신)'를 확인할 때 씁니다.

    Args:
        host: PC 이름 (예: WS-007)
        pid: 프로세스 번호
    """
    # TODO[REC-3]: host와 pid가 같은 기록 중 type이 network, file, registry, script인 것을 시간순으로 (최대 50건).
    # 돌려줄 모양: {"host", "pid", "events": [summarize(e) ...]}
    raise NotImplementedError("TODO[REC-3]")


def get_host_timeline(host: str, around_ts: str, minutes: int = 10) -> dict:
    """특정 시각 앞뒤로 그 PC에서 일어난 모든 일을 시간순으로 봅니다.
    알림 직전·직후에 다른 수상한 활동(다른 프로그램, 다른 통신)이 있었는지 넓게 볼 때 씁니다.

    Args:
        host: PC 이름 (예: WS-007)
        around_ts: 기준 시각 (ISO 형식, 예: 2026-11-16T09:12:02Z). 보통 알림 시각
        minutes: 기준 시각 앞뒤로 몇 분까지 볼지 (기본 10)
    """
    # TODO[REC-4]: host가 같고 ts가 [around_ts - minutes, around_ts + minutes] 안인 기록을 시간순으로 (최대 TIMELINE_LIMIT건).
    # 결과가 잘렸으면 truncated=True로 알려 줍니다 (LLM이 범위를 줄여 다시 부를 수 있게).
    # 돌려줄 모양: {"host", "from", "to", "events": [summarize(e) ...], "truncated": bool}
    raise NotImplementedError("TODO[REC-4]")




TELEMETRY_TOOLS = [tool(get_process_tree), tool(get_process_activity), tool(get_host_timeline)]
