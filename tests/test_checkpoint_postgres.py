"""H-2: Postgres 체크포인트를 새 saver와 재시작한 API가 읽을 수 있는지 확인합니다."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import psycopg
import pytest
from langgraph.types import Command
from opensearchpy import OpenSearch
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from soc.agent.checkpoint import close_checkpointer, get_checkpointer
from soc.agent.graph import build_graph, run_config
from soc.config import settings

ROOT = Path(__file__).resolve().parents[1]
ALERT = {
    "ts": "2026-11-16T09:12:02Z", "host": "WS-007", "source": "rule",
    "rule_id": "R003", "title": "LSASS 덤프 의심", "severity": "critical",
    "techniques": ["T1003.001"], "event_ids": ["evt-00000023"], "pid": 40702,
}


class _RedactedDsn(str):
    def __repr__(self) -> str:
        return "<isolated Postgres test DSN>"


class _RedactedEnv(dict):
    def __repr__(self) -> str:
        return "<API test environment>"


@pytest.fixture
def postgres_test_dsn():
    """실습 DB와 분리된 일회용 DB를 만들고 테스트 후 삭제합니다."""
    try:
        admin = psycopg.connect(settings.postgres_dsn, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("Postgres가 실행 중이지 않습니다")
    name = f"test_d2h2_{uuid.uuid4().hex[:12]}"
    try:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    except psycopg.errors.InsufficientPrivilege:
        admin.close()
        pytest.skip("Postgres 테스트 DB 생성 권한이 없습니다")
    admin.close()
    try:
        host = conninfo_to_dict(settings.postgres_dsn).get("host")
        overrides = {"host": "127.0.0.1"} if host == "localhost" else {}
        yield _RedactedDsn(make_conninfo(settings.postgres_dsn, dbname=name, connect_timeout=3, **overrides))
    finally:
        close_checkpointer()
        with psycopg.connect(settings.postgres_dsn, autocommit=True, connect_timeout=3) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def test_new_saver_resumes_pending_approval(postgres_test_dsn, monkeypatch):
    monkeypatch.setattr(settings, "backend", "real")
    monkeypatch.setattr(settings, "checkpointer", "auto")
    monkeypatch.setattr(settings, "postgres_dsn", postgres_test_dsn)
    close_checkpointer()
    alert_id = f"test-h2-{uuid.uuid4().hex}"
    cfg = run_config(alert_id)

    first = build_graph(get_checkpointer())
    first.invoke({"alert": ALERT | {"alert_id": alert_id}}, cfg)
    assert first.get_state(cfg).next == ("approval",)

    close_checkpointer()
    second = build_graph(get_checkpointer())
    assert second.get_state(cfg).next == ("approval",)
    out = second.invoke(Command(resume={"approved": True, "approver": "테스트 승인자"}), cfg)
    assert out["report"]["approval"]["approved"] is True
    assert not second.get_state(cfg).next


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _start_api(port: int, env: dict[str, str]) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "soc.api.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise AssertionError(f"API가 시작되지 않았습니다: {proc.communicate()[0]}")
        try:
            if httpx.get(url + "/readyz", timeout=1).status_code == 200:
                return proc
        except httpx.TransportError:
            pass
        time.sleep(0.1)
    output = _stop_api(proc)
    raise AssertionError(f"API /readyz가 20초 안에 준비되지 않았습니다: {output}")


def _stop_api(proc: subprocess.Popen) -> str:
    if proc.poll() is None:
        proc.terminate()
    try:
        output, _ = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        output, _ = proc.communicate(timeout=5)
    return output


def test_api_restart_resumes_approval_and_rejection(postgres_test_dsn):
    client = OpenSearch(hosts=[settings.opensearch_url])
    if not client.ping():
        pytest.skip("API 통합 검증에 필요한 OpenSearch가 실행 중이지 않습니다")
    suffix = uuid.uuid4().hex[:12]
    alerts_index = f"test-d2h2-alerts-{suffix}"
    reports_index = f"test-d2h2-reports-{suffix}"
    port = _free_port()
    env = _RedactedEnv(os.environ.copy())
    env.update({
        "PYTHONPATH": str(ROOT / "src"), "BACKEND": "real", "CHECKPOINTER": "auto",
        "POSTGRES_DSN": postgres_test_dsn, "FAKE_LLM": "true",
        "TELEMETRY_TOOLS": "mock", "KB_TOOLS": "mock",
        "INDEX_ALERTS": alerts_index, "INDEX_REPORTS": reports_index,
        "TRIAGE_API_KEY": "test-only-h2-api-key",
    })
    url = f"http://127.0.0.1:{port}"
    proc = None
    try:
        proc = _start_api(port, env)
        alert_ids = [f"test-h2-approved-{suffix}", f"test-h2-rejected-{suffix}"]
        now = datetime.now(timezone.utc).isoformat()
        for alert_id in alert_ids:
            client.index(
                index=alerts_index, id=alert_id, refresh=True,
                body=ALERT | {"alert_id": alert_id, "status": "new", "attempts": 0,
                              "created_at": now, "updated_at": now},
            )
            response = httpx.post(url + f"/alerts/{alert_id}/triage", timeout=30,
                                  headers={"Authorization": "Bearer test-only-h2-api-key"})
            response.raise_for_status()
            assert response.json()["status"] == "pending_approval"
        _stop_api(proc)
        proc = _start_api(port, env)

        for alert_id, approved in zip(alert_ids, (True, False), strict=True):
            decision = {"approved": approved, "approver": "테스트 승인자", "comment": "재시작 후 결정"}
            response = httpx.post(url + f"/approvals/{alert_id}", json=decision, timeout=30)
            response.raise_for_status()
            assert response.json()["approval"]["approved"] is approved
            assert response.json()["approval"]["comment"] == "재시작 후 결정"
            assert httpx.get(url + f"/alerts/{alert_id}", timeout=10).json()["status"] == "completed"
            assert httpx.post(url + f"/approvals/{alert_id}", json=decision, timeout=10).status_code == 409
    finally:
        if proc is not None:
            _stop_api(proc)
        for index in (alerts_index, reports_index):
            if client.indices.exists(index=index):
                client.indices.delete(index=index)
