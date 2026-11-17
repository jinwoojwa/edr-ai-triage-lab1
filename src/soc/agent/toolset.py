"""에이전트가 쓸 도구 묶음. .env의 TELEMETRY_TOOLS, KB_TOOLS로 진짜/가짜를 고릅니다.

2일차 1-1: 한쪽 도구가 아직 덜 됐으면 그쪽만 mock으로 두고 진행합니다.
계약을 지켰다면 에이전트 코드는 고칠 필요가 없습니다.
"""
from __future__ import annotations

from ..config import settings


def telemetry_tools() -> list:
    if settings.telemetry_tools == "real":
        from ..telemetry.tools import TELEMETRY_TOOLS
        return TELEMETRY_TOOLS
    from ..mocks import TELEMETRY_TOOLS
    return TELEMETRY_TOOLS


def search_playbook_fn():
    if settings.kb_tools == "real":
        from ..kb.search import search_playbook
        return search_playbook
    from ..mocks import search_playbook
    return search_playbook
