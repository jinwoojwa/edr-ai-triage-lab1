"""👥 사람 승인 테스트 (2일차 1-3, TODO[H-1]).

    pytest tests/test_approval.py -q
"""
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from soc.agent.graph import build_graph, run_config

ALERT = {"alert_id": "al-test-approval", "ts": "2026-11-16T09:12:02Z", "host": "WS-007", "rule_id": "R003",
         "title": "LSASS 덤프 의심", "severity": "critical", "techniques": ["T1003.001"],
         "event_ids": ["evt-00000023"], "pid": 40702}


def test_stops_for_isolation_then_resumes():
    g = build_graph(InMemorySaver())
    cfg = run_config(ALERT["alert_id"])
    g.invoke({"alert": ALERT}, cfg)
    st = g.get_state(cfg)
    assert st.next == ("approval",), "격리 권고인데 승인에서 멈추지 않았습니다"
    req = st.tasks[0].interrupts[0].value
    assert req["host"] == "WS-007" and req["evidence_event_ids"]
    assert any(a["action"] == "isolate_host" for a in req["actions"])
    out = g.invoke(Command(resume={"approved": True, "approver": "김팀장"}), cfg)
    assert out["report"]["approval"]["approved"] is True
    assert not g.get_state(cfg).next


def test_rejection_is_recorded():
    g = build_graph(InMemorySaver())
    cfg = run_config(ALERT["alert_id"] + "-2")
    g.invoke({"alert": ALERT | {"alert_id": ALERT["alert_id"] + "-2"}}, cfg)
    out = g.invoke(Command(resume={"approved": False, "approver": "김팀장", "comment": "업무 중요 PC"}), cfg)
    assert out["report"]["approval"]["approved"] is False
    assert out["report"]["approval"]["comment"] == "업무 중요 PC"


def test_new_saver_has_no_memory():
    """메모리 저장은 프로세스가 바뀌면 사라집니다 → Postgres가 필요한 이유 (2일차 1-3 실험)."""
    g1 = build_graph(InMemorySaver())
    cfg = run_config("al-test-restart")
    g1.invoke({"alert": ALERT | {"alert_id": "al-test-restart"}}, cfg)
    g2 = build_graph(InMemorySaver())          # '재시작'한 프로세스
    assert not g2.get_state(cfg).next
