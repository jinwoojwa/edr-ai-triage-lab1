"""에이전트 그래프: 노드를 엣지로 잇습니다. (1일차 4-2, 함께)

    python -m soc.agent.graph       # Mermaid 그림 출력 → docs/ARCHITECTURE.md에 붙이기
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from . import nodes
from .state import TriageState


def build_graph(checkpointer=None):
    g = StateGraph(TriageState)
    g.add_node("investigate", nodes.investigate)
    g.add_node("tools", nodes.run_tools)
    g.add_node("judge", nodes.judge)
    g.add_node("guardrail", nodes.check_guardrail)
    g.add_node("recommend", nodes.recommend)
    g.add_node("approval", nodes.approval)
    g.add_node("report", nodes.report)
    g.add_edge(START, "investigate")
    g.add_conditional_edges("investigate", nodes.after_investigate, {"tools": "tools", "judge": "judge"})
    g.add_edge("tools", "investigate")
    g.add_edge("judge", "guardrail")
    g.add_conditional_edges("guardrail", nodes.after_guardrail,
                            {"investigate": "investigate", "recommend": "recommend"})
    g.add_edge("recommend", "approval")
    g.add_edge("approval", "report")
    g.add_edge("report", END)
    return g.compile(checkpointer=checkpointer)


def run_config(alert_id: str) -> dict:
    """thread_id = 알림 id. 같은 알림은 같은 '수첩 페이지'를 씁니다. LangSmith 추적에도 이름과 태그가 붙습니다."""
    return {"configurable": {"thread_id": alert_id}, "run_name": f"triage {alert_id}",
            "tags": ["edr-triage"], "metadata": {"alert_id": alert_id}, "recursion_limit": 50}


if __name__ == "__main__":
    print(build_graph().get_graph().draw_mermaid())
