"""👥 가드레일 테스트 (2일차 1-2, TODO[G-1], [G-2]).

일부러 근거를 지어내는 가짜 LLM('거짓말쟁이')으로 에이전트를 돌려, 가드레일이 막는지 봅니다.

    pytest tests/test_guardrail.py -q
"""
import pytest
from langgraph.types import Command

from soc.agent import guardrail, nodes
from soc.agent.checkpoint import get_checkpointer
from soc.agent.fake_llm import FAKE_ID, FakeLLM
from soc.agent.graph import build_graph, run_config

ALERT = {"alert_id": "al-test-guardrail", "ts": "2026-11-16T09:12:02Z", "host": "WS-007", "rule_id": "R003",
         "title": "LSASS 덤프 의심", "severity": "critical", "techniques": ["T1003.001"],
         "event_ids": ["evt-00000023"], "pid": 40702}


def test_g1_unknown_evidence_is_caught():
    v = {"verdict": "malicious", "evidence_event_ids": ["evt-00000023", "evt-99999999"]}
    problems = guardrail.check_evidence_exists(v, ["evt-00000022", "evt-00000024"], ALERT)
    assert len(problems) == 1 and "evt-99999999" in problems[0]


def test_g1_alert_events_count_as_known():
    v = {"verdict": "malicious", "evidence_event_ids": ["evt-00000023", "evt-00000024"]}
    assert guardrail.check_evidence_exists(v, ["evt-00000024"], ALERT) == []


def test_g2_malicious_needs_two():
    assert guardrail.check_malicious_needs_two({"verdict": "malicious", "evidence_event_ids": ["a"]})
    assert guardrail.check_malicious_needs_two({"verdict": "malicious", "evidence_event_ids": ["a", "a"]})
    assert not guardrail.check_malicious_needs_two({"verdict": "malicious", "evidence_event_ids": ["a", "b"]})
    assert not guardrail.check_malicious_needs_two({"verdict": "suspicious", "evidence_event_ids": ["a"]})


@pytest.fixture
def liar(monkeypatch):
    monkeypatch.setattr(nodes, "get_llm", lambda: FakeLLM(fabricate=True))


def test_liar_is_not_trusted(liar):
    g = build_graph(get_checkpointer())
    cfg = run_config(ALERT["alert_id"])
    out = g.invoke({"alert": ALERT}, cfg)
    if g.get_state(cfg).next:
        out = g.invoke(Command(resume={"approved": False, "approver": "테스트"}), cfg)
    r = out["report"]
    assert FAKE_ID not in r["evidence_event_ids"], "지어낸 근거가 리포트에 남았습니다"
    assert r["verdict"] != "malicious", "근거가 부족한데 악성 판정이 그대로 나갔습니다"
    assert any(not g["ok"] for g in r["guardrail_log"])
