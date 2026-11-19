"""공개 무료 API와 유료 트리아지 인증의 경계를 검증합니다."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr

from soc.agent.graph import build_graph, run_config
from soc.api import main as api
from soc.config import settings


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "triage_api_key", SecretStr("test-only-public-access-key"))
    # These tests use in-memory documents; they never touch a service DB.
    monkeypatch.setattr(api, "get_alert", lambda aid: {"alert_id": aid, "status": "pending_approval"})
    monkeypatch.setattr(api, "get_report", lambda aid: {"alert_id": aid})
    monkeypatch.setattr(api, "list_alerts", lambda *a, **k: [{"alert_id": "test-public"}])
    monkeypatch.setattr(api, "count_by_status", lambda: {"new": 0})
    return TestClient(api.app)


@pytest.mark.parametrize("path", ["/docs", "/openapi.json", "/healthz", "/alerts", "/alerts/test-public",
                                  "/reports/test-public", "/approvals", "/stats"])
def test_free_routes_need_no_key(client, path):
    assert client.get(path).status_code == 200


def test_openapi_protects_only_triage_and_contains_no_secret(client):
    schema = client.get("/openapi.json").json()
    assert not schema.get("security")
    assert "/dify/retrieval" not in schema["paths"]
    protected = [(path, method) for path, ops in schema["paths"].items()
                 for method, op in ops.items() if isinstance(op, dict) and op.get("security")]
    assert protected == [("/alerts/{alert_id}/triage", "post")]
    assert "test-only-public-access-key" not in str(schema)
    assert schema["components"]["securitySchemes"]["TriageAPIKey"]["scheme"] == "bearer"


@pytest.mark.parametrize("header", [None, "Bearer wrong", "Bearer", "Basic dGVzdDp0ZXN0"])
def test_denied_triage_has_no_side_effects_or_paid_calls(client, monkeypatch, header):
    def forbidden(*args, **kwargs):
        pytest.fail("Denied request must not inspect/mutate alerts or start the agent")
    for name in ("get_alert", "update_alert", "graph"):
        monkeypatch.setattr(api, name, forbidden)
    monkeypatch.setattr("soc.worker.process", forbidden)
    response = client.post("/alerts/test-public/triage", headers={} if header is None else {"Authorization": header})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_unconfigured_key_fails_closed_without_disabling_free_routes(client, monkeypatch):
    monkeypatch.setattr(settings, "triage_api_key", SecretStr(""))
    monkeypatch.setattr(api, "get_alert", lambda aid: pytest.fail("No state access when key is unconfigured"))
    assert client.post("/alerts/test-public/triage").status_code == 503
    assert client.get("/healthz").status_code == 200
    assert client.get("/docs").status_code == 200


def test_valid_key_allows_triage(client, monkeypatch):
    updates = []
    sentinel = object()
    monkeypatch.setattr(api, "graph", lambda: sentinel)
    monkeypatch.setattr(api, "update_alert", lambda aid, **fields: updates.append((aid, fields)))
    def process(graph, alert):
        assert graph is sentinel and alert["alert_id"] == "test-public"
        return "pending_approval"
    monkeypatch.setattr("soc.worker.process", process)
    response = client.post("/alerts/test-public/triage", headers={"Authorization": "Bearer test-only-public-access-key"})
    assert response.status_code == 200 and response.json()["status"] == "pending_approval"
    assert updates == [("test-public", {"status": "in_progress", "worker": "api"})]


@pytest.mark.parametrize("next_nodes,interrupts,status", [
    ((), (), 410), (("investigate",), (object(),), 409),
    (("judge",), (object(),), 409), (("recommend",), (object(),), 409),
    (("approval",), (), 409), (("approval", "judge"), (object(),), 409),
])
def test_free_approval_cannot_resume_a_paid_node(client, monkeypatch, next_nodes, interrupts, status):
    checkpoint = SimpleNamespace(next=next_nodes, interrupts=interrupts)
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid approval must not resume or mutate state")
    monkeypatch.setattr(api, "graph", lambda: SimpleNamespace(get_state=lambda cfg: checkpoint, invoke=forbidden))
    monkeypatch.setattr(api, "save_report", forbidden)
    monkeypatch.setattr(api, "update_alert", forbidden)
    assert client.post("/approvals/test-public", json={"approved": True}).status_code == status


@pytest.mark.parametrize("approved", [True, False])
def test_free_approval_resumes_real_graph_without_llm_or_embedding(client, monkeypatch, approved):
    from soc.agent import nodes
    from soc.kb import search

    monkeypatch.setattr(settings, "checkpointer", "memory")
    graph = build_graph(InMemorySaver())
    alert = {"alert_id": "test-public", "host": "WS-007", "pid": 40702,
             "title": "LSASS dump", "severity": "critical", "rule_id": "R003", "techniques": ["T1003.001"],
             "ts": "2026-11-16T09:12:02Z", "event_ids": ["evt-00000023"]}
    cfg = run_config(alert["alert_id"])
    graph.invoke({"alert": alert}, cfg)
    assert graph.get_state(cfg).next == ("approval",)
    def paid_call(*args, **kwargs):
        pytest.fail("Approval/report must not invoke an LLM or paid retrieval")
    monkeypatch.setattr(nodes, "get_llm", paid_call)
    monkeypatch.setattr(nodes, "search_playbook_fn", paid_call)
    monkeypatch.setattr(search, "embed_query", paid_call)
    monkeypatch.setattr(api, "graph", lambda: graph)
    saved, updates = [], []
    monkeypatch.setattr(api, "save_report", saved.append)
    monkeypatch.setattr(api, "update_alert", lambda aid, **fields: updates.append(fields))
    response = client.post("/approvals/test-public", json={"approved": approved, "approver": "공개 실습"})
    assert response.status_code == 200
    assert response.json()["approval"]["approved"] is approved
    assert not graph.get_state(cfg).next
    assert len(saved) == 1 and updates == [{"status": "completed"}]
