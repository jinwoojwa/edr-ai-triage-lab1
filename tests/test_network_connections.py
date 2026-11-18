"""D2-7 외부 네트워크 연결 도구: 집계 계약과 실제 OpenSearch 조회."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from soc.agent.nodes import _ids
from soc.config import settings
from soc.osclient import get_client
from soc.telemetry import tools
from soc.telemetry.index_template import build_template


T0 = datetime(2026, 11, 16, 10, 0, tzinfo=timezone.utc)


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return T0 if tz is None else T0.astimezone(tz)


def event(eid, seconds, ip, host="WS-NET", pid=101):
    return {"event_id": eid, "ts": (T0 + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z"),
            "host": host, "type": "network",
            "process": {"pid": pid, "ppid": 1, "name": "agent.exe", "cmdline": "agent.exe",
                        "user": "SYSTEM", "signed": True},
            "network": {"dst_ip": ip, "dst_port": 443, "bytes_out": 300}}


def stub_search(monkeypatch, events):
    def search(body):
        filters = body["query"]["bool"]["filter"]
        host = next(f["term"]["host"] for f in filters if "host" in f.get("term", {}))
        kind = next(f["term"]["type"] for f in filters if "type" in f.get("term", {}))
        span = next(f["range"]["ts"] for f in filters if "range" in f)
        assert kind == "network"
        selected = [e for e in events if e["host"] == host and e["type"] == kind
                    and span["gte"] <= e["ts"] <= span["lte"]]
        return sorted(selected, key=lambda e: (e["ts"], e["event_id"]), reverse=True)[:body["size"]]

    monkeypatch.setattr(tools, "_search", search)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(tools, "datetime", FixedDatetime)


def test_external_connections_are_grouped_with_real_evidence(monkeypatch):
    events = [event("a", -90, "198.51.100.23"), event("b", -60, "198.51.100.23"),
              event("c", -30, "198.51.100.23"), event("d", -15, "203.0.113.40"),
              event("inside", -20, "10.0.2.10"), event("other-host", -10, "198.51.100.23", "WS-OTHER"),
              event("too-old", -121, "198.51.100.23"), event("future", 1, "198.51.100.23")]
    stub_search(monkeypatch, events)

    result = tools.get_network_connections("WS-NET", 2)

    assert result["host"] == "WS-NET"
    assert result["from"] == "2026-11-16T09:58:00Z"
    assert result["to"] == "2026-11-16T10:00:00Z"
    assert result["truncated"] is False
    assert [g["dst_ip"] for g in result["connections"]] == ["198.51.100.23", "203.0.113.40"]
    first, second = result["connections"]
    assert first["count"] == 3 and first["avg_interval_seconds"] == 30.0
    assert (first["first_ts"], first["last_ts"]) == (events[0]["ts"], events[2]["ts"])
    assert [e["event_id"] for e in first["events"]] == ["a", "b", "c"]
    assert second["count"] == 1 and second["avg_interval_seconds"] is None
    assert set(_ids(result)) == {"a", "b", "c", "d"}


def test_empty_result_and_invalid_inputs(monkeypatch):
    stub_search(monkeypatch, [event("inside", -30, "192.168.1.10")])
    result = tools.get_network_connections("WS-NET", 2)
    assert result["connections"] == [] and result["truncated"] is False
    assert {t.name for t in tools.TELEMETRY_TOOLS} == {
        "get_process_tree", "get_process_activity", "get_host_timeline", "get_network_connections"}
    for host in ("", "  ", None, 5):
        with pytest.raises(ValueError):
            tools.get_network_connections(host, 2)
    for minutes in (0, -1, True, 2.5, "2", 10**12):
        with pytest.raises(ValueError):
            tools.get_network_connections("WS-NET", minutes)


def test_search_failure_is_not_reported_as_empty(monkeypatch):
    def unavailable(_body):
        raise RuntimeError("OpenSearch unavailable")

    monkeypatch.setattr(tools, "_search", unavailable)
    with pytest.raises(RuntimeError, match="OpenSearch unavailable"):
        tools.get_network_connections("WS-NET", 2)


def test_evidence_and_destination_limits(monkeypatch):
    monkeypatch.setattr(tools, "NETWORK_DESTINATIONS", 1)
    events = [event(f"a{i}", -90 + i * 10, "198.51.100.23") for i in range(6)]
    events += [event("b0", -20, "203.0.113.40")]
    stub_search(monkeypatch, events)
    result = tools.get_network_connections("WS-NET", 2)
    assert result["truncated"] is True
    assert len(result["connections"]) == 1
    group = result["connections"][0]
    assert group["count"] == 6 and group["events_truncated"] is True
    assert [e["event_id"] for e in group["events"]] == ["a1", "a2", "a3", "a4", "a5"]


def test_event_limit_marks_partial_counts(monkeypatch):
    monkeypatch.setattr(tools, "NETWORK_LIMIT", 2)
    stub_search(monkeypatch, [event("a", -90, "198.51.100.23"),
                              event("b", -60, "198.51.100.23"),
                              event("c", -30, "198.51.100.23")])
    result = tools.get_network_connections("WS-NET", 2)
    assert result["truncated"] is True
    assert result["connections"][0]["count"] == 2
    assert [e["event_id"] for e in result["connections"][0]["events"]] == ["b", "c"]


@pytest.mark.skipif(settings.backend != "real", reason="실제 OpenSearch 통합 검사")
def test_real_opensearch_query_uses_isolated_index(monkeypatch):
    client = get_client()
    index = f"{settings.index_events}-d27test-{uuid4().hex[:10]}"
    mapping = build_template()["template"]["mappings"]
    client.indices.create(index=index, body={"mappings": mapping})
    try:
        for e in (event("real-a", -60, "198.51.100.23"),
                  event("real-b", -30, "198.51.100.23"),
                  event("real-local", -20, "10.0.2.10")):
            client.index(index=index, id=e["event_id"], body=e)
        client.indices.refresh(index=index)
        monkeypatch.setattr(tools, "EVENTS", index)
        network_tool = next(t for t in tools.TELEMETRY_TOOLS if t.name == "get_network_connections")
        result = network_tool.invoke({"host": "WS-NET", "minutes": 2})
        assert result["truncated"] is False
        assert len(result["connections"]) == 1
        assert result["connections"][0]["count"] == 2
        assert result["connections"][0]["avg_interval_seconds"] == 30.0
        assert set(_ids(result)) == {"real-a", "real-b"}
    finally:
        client.indices.delete(index=index, ignore_unavailable=True)
