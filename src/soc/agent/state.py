"""에이전트의 상태(State): 노드들이 함께 읽고 쓰는 공책.

체크포인터(Postgres)가 노드가 끝날 때마다 이 상태를 저장합니다.
그래서 사람 승인에서 멈췄다가, 파드가 바뀌어도 이 상태를 읽어 이어 갈 수 있습니다.
"""
from __future__ import annotations

import operator
from typing import Annotated, Literal

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


def merge_usage(a: dict | None, b: dict | None) -> dict:
    a, b = a or {}, b or {}
    return {k: a.get(k, 0) + b.get(k, 0) for k in set(a) | set(b)}


class Verdict(BaseModel):
    """판정 노드의 출력 형식 (LLM이 이 모양으로 답하게 합니다)."""
    verdict: Literal["malicious", "suspicious", "benign"] = Field(description="악성 / 의심 / 정상")
    confidence: float = Field(ge=0, le=1, description="0~1 사이 신뢰도")
    techniques: list[str] = Field(default_factory=list, description="ATT&CK 기법 ID (예: T1003.001)")
    evidence_event_ids: list[str] = Field(default_factory=list, description="판정 근거로 쓴 event_id. 도구 결과에 나온 것만")
    reasoning: str = Field(description="판정 이유를 한국어 3~5문장으로")


class Action(BaseModel):
    action: Literal["monitor", "collect_forensics", "block_ip", "kill_process", "isolate_host",
                    "reset_password", "close_as_benign"]
    reason: str
    approver: str | None = Field(default=None, description="정책상 승인권자. 승인이 필요 없으면 비움")
    source: str | None = Field(default=None, description="근거가 된 플레이북 파일 이름")


class Recommendation(BaseModel):
    """권고 노드의 출력 형식."""
    actions: list[Action]
    summary: str = Field(description="분석가에게 보여 줄 권고 요약 (한국어 2~3문장)")


# 정책(01번 PDF 2장)상 승인이 필요한 조치
DANGEROUS_ACTIONS = {"block_ip", "kill_process", "isolate_host", "reset_password"}


class TriageState(TypedDict, total=False):
    alert: dict
    messages: Annotated[list[AnyMessage], add_messages]   # 조사 대화 (LLM ⇄ 도구)
    seen_event_ids: Annotated[list[str], operator.add]    # 도구로 실제 조회한 기록의 id (가드레일이 씀)
    tool_rounds: int
    verdict: dict
    guardrail: dict
    guardrail_log: Annotated[list[dict], operator.add]   # 가드레일 검사 기록 (평가에서 '지어낸 근거 비율'에 씀)
    guardrail_retries: int
    playbook: list[dict]
    recommendation: dict
    approval: dict
    report: dict
    trace: Annotated[list[str], operator.add]             # 지나온 노드 (1일차 뼈대 확인용)
    usage: Annotated[dict, merge_usage]                   # 토큰 사용량 (비용 계산)
