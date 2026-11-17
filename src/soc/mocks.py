"""가짜 도구 4개: 도구 계약의 '모양'을 보여 주는 견본.

1일차에 계약(docs/CONTRACT.md)을 정할 때 이 파일을 함께 읽습니다.
그 뒤에는 각자 상대의 진짜 도구가 아직 없을 때 이 가짜를 대신 씁니다. 그래서 둘이 동시에 개발할 수 있습니다.

- 🔍 기록 담당의 진짜 도구: src/soc/telemetry/tools.py
- 📘 문서 담당의 진짜 도구: src/soc/kb/search.py

가짜는 어떤 질문을 받아도 01 문서의 예시 알림(WS-007, LSASS 덤프) 이야기를 돌려줍니다.
돌려주는 모양(키 이름, event_id, source)이 진짜와 같아야 나중에 바꿔 끼울 수 있습니다.
"""
from __future__ import annotations

from langchain_core.tools import tool

_CMD = r"rundll32.exe C:\Windows\System32\comsvcs.dll, MiniDump 668 C:\Windows\Temp\d.dmp full"
_RUNDLL = {"event_id": "evt-00000023", "ts": "2026-11-16T09:12:02Z", "type": "process", "pid": 40702, "ppid": 19329,
           "name": "rundll32.exe", "cmdline": _CMD, "user": "kim", "signed": True}
_CMDEXE = {"event_id": "evt-00000022", "ts": "2026-11-16T09:12:01Z", "type": "process", "pid": 19329, "ppid": 8015,
           "name": "cmd.exe", "cmdline": "cmd.exe", "user": "kim", "signed": True}
_DMP = {"event_id": "evt-00000024", "ts": "2026-11-16T09:12:03Z", "type": "file", "pid": 40702, "ppid": 19329,
        "name": "rundll32.exe", "cmdline": _CMD, "user": "kim", "signed": True,
        "detail": r"create C:\Windows\Temp\d.dmp"}


def get_process_tree(host: str, pid: int) -> dict:
    """[가짜] 프로세스의 족보: 부모들(ancestors)과 자식들(children)."""
    return {"host": host, "pid": pid, "process": _RUNDLL, "ancestors": [_CMDEXE], "children": [],
            "note": "부모 프로세스(pid 8015, explorer.exe)의 생성 기록이 없습니다."}


def get_process_activity(host: str, pid: int) -> dict:
    """[가짜] 한 프로세스가 한 일 (통신, 파일, 레지스트리, 스크립트)."""
    return {"host": host, "pid": pid, "events": [_DMP]}


def get_host_timeline(host: str, around_ts: str, minutes: int = 10) -> dict:
    """[가짜] 특정 시각 앞뒤로 그 PC에서 일어난 일."""
    return {"host": host, "from": around_ts, "to": around_ts, "events": [_CMDEXE, _RUNDLL, _DMP], "truncated": False}


def search_playbook(query: str, k: int = 3) -> list[dict]:
    """[가짜] 질문과 관련된 플레이북·정책 조각. 결과마다 source(파일 이름)가 있습니다."""
    rows = [
        {"source": "01_response_policy_tables.pdf", "page": 1, "category": "Table", "score": 0.91,
         "text": "호스트 네트워크 격리 | 영향도 높음 | 승인 필요: 예 | 승인권자: SOC 팀장"},
        {"source": "02_playbook_credential_dump.pdf", "page": 1, "category": "NarrativeText", "score": 0.88,
         "text": "권고 조치는 호스트 네트워크 격리(SOC 팀장 승인), 해당 호스트에 로그인했던 계정의 비밀번호 초기화(SOC 팀장 및 계정 소유 부서장 승인), 덤프 파일 포렌식 수집이다."},
        {"source": "01_response_policy_tables.pdf", "page": 2, "category": "NarrativeText", "score": 0.80,
         "text": "악성(malicious) 판정에는 서로 독립적인 근거 이벤트가 두 개 이상 필요하다."},
    ]
    return rows[:k]


TELEMETRY_TOOLS = [tool(get_process_tree), tool(get_process_activity), tool(get_host_timeline)]
KB_TOOLS = [tool(search_playbook)]
