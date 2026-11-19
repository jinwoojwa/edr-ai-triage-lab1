"""Verify D2-2 real tool wiring against an isolated OpenSearch event index.

Run from the repository root:
    .venv\\Scripts\\python.exe scripts\\verify_d2_2.py
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import ToolMessage

from soc.agent.graph import build_graph, run_config
from soc.agent.toolset import search_playbook_fn, telemetry_tools
from soc.config import settings
from soc.eval.agent_eval import labeled_alerts
from soc.kb.search import search_playbook
from soc.osclient import get_client
from soc.telemetry.index_template import build_template, index_events


def main() -> None:
    assert settings.backend == "real", "BACKEND must be real"
    assert settings.telemetry_tools == "real" and settings.kb_tools == "real"
    assert not settings.fake_llm, "Expected real LLM for this probe"
    client = get_client()
    assert client.ping(), "OpenSearch unavailable"
    assert client.count(index=settings.index_kb)["count"] > 0, "KB empty"

    events, alerts = labeled_alerts()
    alert, truth = next((a, t) for a, t in alerts if t.name == "credential_dump" and a.get("pid"))
    scenario_events = [e.model_dump(mode="json", exclude_none=True) for e in events if e.event_id in set(truth.event_ids)]
    original_ids = {e["event_id"] for e in scenario_events}
    assert scenario_events and set(alert["event_ids"]) <= original_ids

    original_prefix = settings.index_events
    settings.index_events = f"test-d2-2-{uuid.uuid4().hex[:10]}"
    index_name = None
    try:
        day = scenario_events[0]["ts"][:10].replace("-", ".")
        index_name = f"{settings.index_events}-{day}"
        client.indices.create(index=index_name, body=build_template()["template"])
        indexed = index_events(scenario_events, client)

        tool_names = [t.name for t in telemetry_tools()]
        assert tool_names == ["get_process_tree", "get_process_activity", "get_host_timeline"]
        assert search_playbook_fn() is search_playbook

        direct = {}
        args = {
            "get_process_tree": {"host": alert["host"], "pid": alert["pid"]},
            "get_process_activity": {"host": alert["host"], "pid": alert["pid"]},
            "get_host_timeline": {"host": alert["host"], "around_ts": alert["ts"], "minutes": 10},
        }
        for tool in telemetry_tools():
            result = tool.invoke(args[tool.name])
            direct[tool.name] = result
            assert "error" not in result, (tool.name, result)

        graph = build_graph(InMemorySaver())
        output = graph.invoke({"alert": alert}, run_config(f"d2-2-{uuid.uuid4().hex}"))
        report = output["report"]
        seen = set(output.get("seen_event_ids", []))
        cited = set(report.get("evidence_event_ids", []))
        tool_messages = [m for m in output.get("messages", []) if isinstance(m, ToolMessage)]
        tool_errors = [m.content for m in tool_messages if '"error"' in m.content]
        assert not tool_errors, tool_errors
        assert seen, "No real event IDs returned by agent tools"
        assert cited, "No cited event IDs"
        assert seen <= original_ids, (seen, original_ids)
        assert cited <= original_ids, (cited, original_ids)
        assert cited <= seen | set(alert["event_ids"])
        assert output.get("playbook"), "No real KB hits"
        assert report.get("sources"), "No report sources"
        assert all(h.get("source") and h.get("page") for h in output["playbook"])

        summary = {
            "status": "pass",
            "backend": settings.backend,
            "fake_llm": settings.fake_llm,
            "alert_id": alert["alert_id"],
            "scenario": truth.name,
            "indexed_events": indexed,
            "direct_tool_result_counts": {
                "get_process_tree": sum(bool(direct["get_process_tree"].get(k)) for k in ("process", "ancestors", "children")),
                "get_process_activity": len(direct["get_process_activity"]["events"]),
                "get_host_timeline": len(direct["get_host_timeline"]["events"]),
            },
            "agent_tool_calls": len(tool_messages),
            "seen_event_ids": sorted(seen),
            "cited_event_ids": sorted(cited),
            "verdict": report["verdict"],
            "playbook_hits": [{"source": h["source"], "page": h["page"]} for h in output["playbook"]],
            "report_sources": report["sources"],
            "trace": report["trace"],
            "approval": report.get("approval"),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        settings.index_events = original_prefix
        if index_name and client.indices.exists(index=index_name):
            client.indices.delete(index=index_name)


if __name__ == "__main__":
    main()
