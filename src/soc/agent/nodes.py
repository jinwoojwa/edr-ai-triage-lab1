"""에이전트의 노드들. 노드 하나 = 상태를 받아 '바꿀 부분'을 돌려주는 함수.

    조사 ⇄ 도구 → 판정 → 가드레일 → 권고 → 승인 → 리포트

운전 규칙 (1일차 4-2): 상대가 만든 도구를 내가 연결합니다.
- 조사 노드(🔍 도구를 씀)는 📘 문서 담당이 운전  → TODO[AG-1]
- 권고 노드(📘 검색을 씀)는 🔍 기록 담당이 운전  → TODO[AG-2]
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.types import interrupt

from ..config import settings
from . import guardrail
from .llm import cost_usd, get_llm, usage_of
from .prompts import prompt
from .state import DANGEROUS_ACTIONS, Recommendation, TriageState, Verdict
from .toolset import search_playbook_fn, telemetry_tools


def _alert_message(alert: dict) -> HumanMessage:
    keep = ("alert_id", "ts", "host", "rule_id", "title", "severity", "techniques", "event_ids", "pid")
    data = {k: alert.get(k) for k in keep}
    return HumanMessage(content=f"알림:\n```json\n{json.dumps(data, ensure_ascii=False, indent=1)}\n```")


def _ids(obj) -> list[str]:
    """도구 결과 안의 모든 event_id를 꺼냅니다 (가드레일이 '실제로 조회한 기록'으로 씀)."""
    if isinstance(obj, dict):
        return [v for k, v in obj.items() if k == "event_id" and isinstance(v, str)] + \
            [i for k, v in obj.items() if k != "event_id" for i in _ids(v)]
    if isinstance(obj, list):
        return [i for v in obj for i in _ids(v)]
    return []


# ---------------------------------------------------------------------------- 조사
def investigate(state: TriageState) -> dict:
    """조사 노드: LLM이 🔍 조사 도구 중 무엇을 부를지 정합니다."""
    history = list(state.get("messages", []))
    initial = [_alert_message(state["alert"])] if not history else []
    llm = get_llm().bind_tools(telemetry_tools())
    response = llm.invoke([SystemMessage(content=prompt("investigate"))] + history + initial)
    return {"messages": initial + [response], "trace": ["조사"], "usage": usage_of(response)}


def run_tools(state: TriageState) -> dict:
    """도구 노드: LLM이 요청한 도구를 실행하고, 결과의 event_id를 '실제로 조회한 기록'으로 남깁니다."""
    tools = {t.name: t for t in telemetry_tools()}
    last: AIMessage = state["messages"][-1]
    msgs, seen = [], []
    for call in last.tool_calls:
        t = tools.get(call["name"])
        try:
            result = t.invoke(call["args"]) if t else {"error": f"없는 도구: {call['name']}"}
        except Exception as e:  # noqa: BLE001  도구 오류도 LLM에게 알려 줘서 다른 방법을 찾게 합니다
            result = {"error": f"{type(e).__name__}: {e}"}
        seen += _ids(result)
        msgs.append(ToolMessage(content=json.dumps(result, ensure_ascii=False, default=str), tool_call_id=call["id"]))
    return {"messages": msgs, "seen_event_ids": seen, "tool_rounds": state.get("tool_rounds", 0) + 1,
            "trace": ["도구"]}


def after_investigate(state: TriageState) -> str:
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None) and state.get("tool_rounds", 0) < settings.max_tool_rounds:
        return "tools"
    return "judge"


# ---------------------------------------------------------------------------- 판정과 가드레일
def judge(state: TriageState) -> dict:
    llm = get_llm().with_structured_output(Verdict, include_raw=True)
    msgs = [SystemMessage(content=prompt("judge"))] + list(state["messages"]) + [HumanMessage(content="판정하세요.")]
    out = llm.invoke(msgs)
    return {"verdict": out["parsed"].model_dump(), "trace": ["판정"], "usage": usage_of(out["raw"])}


def check_guardrail(state: TriageState) -> dict:
    result = guardrail.check(state["verdict"], state.get("seen_event_ids", []), state["alert"])
    out: dict = {"guardrail": result, "guardrail_log": [result], "trace": ["가드레일"]}
    if result["ok"]:
        return out
    retries = state.get("guardrail_retries", 0)
    if settings.guardrail_on_fail == "retry" and retries < settings.max_guardrail_retries:
        # 부족한 점을 알려 주고 다시 조사하게 합니다
        out["guardrail_retries"] = retries + 1
        out["messages"] = [HumanMessage(content="판정이 검증을 통과하지 못했습니다: " + "; ".join(result["problems"])
                                        + ". 도구로 근거를 더 확인하고, 실제로 조회한 event_id만 쓰세요.")]
        return out
    # 낮추기: 지어낸 근거는 빼고 '의심'으로, 사람 검토 표시
    v = dict(state["verdict"])
    known = set(state.get("seen_event_ids", [])) | set(state["alert"].get("event_ids", []))
    v["evidence_event_ids"] = [i for i in v.get("evidence_event_ids", []) if i in known]
    if v["verdict"] == "malicious":
        v["verdict"] = "suspicious"
    v["needs_review"] = True
    out["verdict"] = v
    return out


def after_guardrail(state: TriageState) -> str:
    g = state.get("guardrail", {})
    if not g.get("ok") and state["messages"] and isinstance(state["messages"][-1], HumanMessage):
        return "investigate"
    return "recommend"


# ---------------------------------------------------------------------------- 권고
def recommend(state: TriageState) -> dict:
    """권고 노드: 📘 플레이북 검색으로 근거를 찾고, LLM이 조치를 권고합니다."""
    v, alert = state["verdict"], state["alert"]
    query = " ".join(filter(None, [alert.get("title", ""), v["verdict"],
                                   " ".join(v.get("techniques", [])), "대응 조치 승인권자"]))
    playbook = search_playbook_fn()(query, k=3)
    context = {"alert": alert, "verdict": v, "playbook": playbook}
    messages = [SystemMessage(content=prompt("recommend")),
                HumanMessage(content="다음 근거로 권고하세요.\n```json\n"
                             + json.dumps(context, ensure_ascii=False, default=str) + "\n```")]
    out = get_llm().with_structured_output(Recommendation, include_raw=True).invoke(messages)
    return {"playbook": playbook, "recommendation": out["parsed"].model_dump(),
            "trace": ["권고"], "usage": usage_of(out["raw"])}


# ---------------------------------------------------------------------------- 사람 승인 (2일차, 운전 🔍)
def approval(state: TriageState) -> dict:
    """위험한 조치가 있으면 멈추고 사람의 결정을 기다립니다. 멈춘 동안 상태는 체크포인터(Postgres)에 저장됩니다.

    ⚠ 재개하면 이 노드가 '처음부터 다시' 실행됩니다 (03 문서 3장).
    그래서 interrupt() 앞에 DB 쓰기처럼 한 번만 해야 하는 일을 두지 않습니다.
    """
    actions = state["recommendation"]["actions"]
    risky = [a for a in actions if a["action"] in DANGEROUS_ACTIONS]
    # TODO[H-1]: 위험한 조치가 있으면 interrupt()로 멈추고, 승인권자가 판단할 내용을 넘깁니다.
    # (01번 정책 PDF 5장: 대상 호스트, 판정과 신뢰도, ATT&CK 기법, 근거 event_id, 권고 조치)
    # 재개되면 interrupt()가 사람의 결정({"approved": bool, "approver": str, "comment": str})을 돌려줍니다.
    # 돌려줄 것: approval {"required", "decision", ...}, trace ["승인"]
    return {"approval": {"required": bool(risky), "decision": "not_implemented"}, "trace": ["승인"]}


# ---------------------------------------------------------------------------- 리포트
def report(state: TriageState) -> dict:
    alert, v = state["alert"], state["verdict"]
    usage = state.get("usage", {})
    rep = {
        "alert_id": alert["alert_id"], "host": alert["host"], "title": alert.get("title"),
        "severity": alert.get("severity"),
        "verdict": v["verdict"], "confidence": v["confidence"], "techniques": v.get("techniques", []),
        "evidence_event_ids": v.get("evidence_event_ids", []), "reasoning": v.get("reasoning"),
        "needs_review": v.get("needs_review", False),
        "guardrail": state.get("guardrail", {}),
        "guardrail_log": state.get("guardrail_log", []),
        "recommendation": state.get("recommendation", {}),
        "sources": sorted({h["source"] for h in state.get("playbook", []) if h.get("source")}),
        "approval": state.get("approval", {}),
        "tool_rounds": state.get("tool_rounds", 0),
        "usage": usage, "cost_usd": cost_usd(usage),
        "trace": state.get("trace", []) + ["리포트"],
    }
    return {"report": rep, "trace": ["리포트"]}
