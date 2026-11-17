"""👥 에이전트 뼈대 테스트 (1일차 4-2, TODO[AG-1] ~ [AG-3]).

가짜 도구(mocks.py)와 가짜 LLM으로 그래프가 끝까지 흐르는지만 봅니다.

    pytest tests/test_graph_skeleton.py -q
"""
from langgraph.types import Command

from soc.agent.checkpoint import get_checkpointer
from soc.agent.graph import build_graph, run_config
from soc.config import settings

ALERT = {"alert_id": "al-test-skeleton", "ts": "2026-11-16T09:12:02Z", "host": "WS-007", "source": "rule",
         "rule_id": "R003", "title": "comsvcs.dll MiniDump를 이용한 LSASS 메모리 덤프 의심", "severity": "critical",
         "techniques": ["T1003.001"], "event_ids": ["evt-00000023"], "pid": 40702}


def _in_order(trace, expected):
    it = iter(trace)
    return all(step in it for step in expected)


def test_graph_runs_to_report():
    assert settings.fake_llm and settings.telemetry_tools == "mock" and settings.kb_tools == "mock"
    g = build_graph(get_checkpointer())
    cfg = run_config(ALERT["alert_id"])
    out = g.invoke({"alert": ALERT}, cfg)
    if g.get_state(cfg).next:                                   # 2일차: 승인에서 멈췄으면 승인하고 이어 가기
        out = g.invoke(Command(resume={"approved": True, "approver": "테스트"}), cfg)
    trace = out["report"]["trace"]
    assert _in_order(trace, ["조사", "도구", "조사", "판정", "권고", "리포트"]), trace
    assert out["tool_rounds"] >= 1 and out["seen_event_ids"]
    assert set(out["report"]["evidence_event_ids"]) <= set(out["seen_event_ids"]) | set(ALERT["event_ids"])
    sources = out["report"]["sources"]
    assert sources and sources == sorted({hit["source"] for hit in out["playbook"]})
    assert all(action["source"] in sources for action in out["recommendation"]["actions"])


def test_mermaid():
    text = build_graph().get_graph().draw_mermaid()
    for node in ("investigate", "tools", "judge", "guardrail", "recommend", "approval", "report"):
        assert node in text
    for edge in ("tools --> investigate", "judge --> guardrail", "recommend --> approval", "approval --> report"):
        assert edge in text
