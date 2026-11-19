"""API: 알림·리포트 조회, 사람 승인, Dify 연결, 상태 확인.

    uvicorn soc.api.main:app --reload --port 8000
    → http://localhost:8000/docs 에서 바로 눌러 볼 수 있습니다

주요 기능
- GET  /alerts?status=new          알림 목록
- GET  /approvals                  승인을 기다리는 알림
- POST /approvals/{alert_id}       승인/거절 → 멈춰 있던 에이전트를 이어서 실행
- POST /alerts/{alert_id}/triage   (워커 없이) 이 자리에서 바로 트리아지 실행 — BACKEND=memory 데모용
- GET  /healthz                    프로세스가 살아 있나 (liveness)
- GET  /readyz                     OpenSearch·Postgres에 연결되나 (readiness)
"""
from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langgraph.types import Command
from pydantic import BaseModel

from ..agent.checkpoint import get_checkpointer
from ..agent.checkpoint import ping as pg_ping
from ..agent.graph import build_graph, run_config
from ..alerts import count_by_status, ensure_indices, get_alert, get_report, list_alerts, save_report, update_alert
from ..config import settings
from ..osclient import get_client
from .dify import router as dify_router

log = logging.getLogger("api")
# uvicorn은 자기 로거만 설정합니다. 우리 로그(체크포인터 종류 등)도 `kubectl logs`에 보이게 합니다 (인프라 3단계 확인)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_app):
    try:
        ensure_indices()
    except Exception as e:  # noqa: BLE001  OpenSearch가 아직 없어도 API는 뜹니다 (readyz가 실패로 알려 줌)
        log.warning("인덱스 준비 실패 (나중에 다시 시도): %s", e)
    try:
        graph()          # 체크포인터를 미리 준비 → Postgres면 기동하자마자 체크포인트 테이블이 생김 (인프라 3단계 \dt 확인)
    except Exception as e:  # noqa: BLE001  Postgres가 아직 없어도 API는 뜹니다 (readyz가 실패로 알려 줌)
        log.warning("체크포인터 준비 실패 (첫 승인 요청 때 다시 시도): %s", e)
    yield


app = FastAPI(title="EDR AI 트리아지 API", version="1.0", lifespan=lifespan)
app.include_router(dify_router, include_in_schema=False)

triage_bearer = HTTPBearer(
    auto_error=False, scheme_name="TriageAPIKey",
    description="유료 트리아지 전용 API 키. 무료 조회·승인에는 필요하지 않습니다.",
)


def require_triage_key(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(triage_bearer)],
) -> None:
    configured = settings.triage_api_key.get_secret_value()
    if not configured:
        raise HTTPException(503, "트리아지 API 키가 설정되지 않았습니다")
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode("utf-8"), configured.encode("utf-8"),
    ):
        raise HTTPException(401, "유효한 트리아지 API 키가 필요합니다",
                            headers={"WWW-Authenticate": "Bearer"})


@lru_cache(maxsize=1)
def graph():
    return build_graph(get_checkpointer())


@app.get("/healthz")
def healthz():
    return {"status": "ok", "backend": settings.backend}


@app.get("/readyz", include_in_schema=False)
def readyz():
    checks = {"opensearch": False, "postgres": pg_ping()}
    try:
        checks["opensearch"] = bool(get_client().ping())
    except Exception:  # noqa: BLE001
        pass
    ok = all(checks.values())
    return JSONResponse(status_code=200 if ok else 503, content={"ready": ok, **checks})


@app.get("/stats")
def stats():
    return count_by_status()


@app.get("/alerts")
def alerts(status: str | None = None, size: int = 50):
    return list_alerts(status, size)


@app.get("/alerts/{alert_id}")
def alert(alert_id: str):
    a = get_alert(alert_id)
    if not a:
        raise HTTPException(404, "알림이 없습니다")
    return a


@app.get("/reports/{alert_id}")
def report(alert_id: str):
    r = get_report(alert_id)
    if not r:
        raise HTTPException(404, "리포트가 없습니다")
    return r


@app.post("/alerts/{alert_id}/triage", dependencies=[Depends(require_triage_key)])
def triage_now(alert_id: str):
    from ..worker import process

    a = get_alert(alert_id)
    if not a:
        raise HTTPException(404, "알림이 없습니다")
    update_alert(alert_id, status="in_progress", worker="api")
    result = process(graph(), a)
    return {"alert_id": alert_id, "status": result, "report": get_report(alert_id)}


@app.get("/approvals")
def approvals():
    return [get_report(a["alert_id"]) or a for a in list_alerts("pending_approval")]


class Decision(BaseModel):
    approved: bool
    approver: str = "SOC 팀장"
    comment: str = ""


@app.post("/approvals/{alert_id}")
def approve(alert_id: str, d: Decision):
    a = get_alert(alert_id)
    if not a:
        raise HTTPException(404, "알림이 없습니다")
    if a["status"] != "pending_approval":
        raise HTTPException(409, f"승인 대기 상태가 아닙니다 (지금: {a['status']})")
    g, cfg = graph(), run_config(alert_id)
    checkpoint = g.get_state(cfg)
    if not checkpoint.next:
        # 수첩(체크포인터)에 멈춘 지점이 없음: 메모리 저장이었는데 프로세스가 재시작된 경우 등
        raise HTTPException(410, "저장된 진행 상황이 없습니다. 체크포인터가 메모리였나요? (2일차 1-3 실험)")
    if checkpoint.next != ("approval",) or not checkpoint.interrupts:
        # 무인증 승인이 조사·판정 같은 유료 노드를 재개하는 경로가 되지 않게 한다.
        raise HTTPException(409, "승인 노드에서 대기 중인 진행 상황이 아닙니다")
    out = g.invoke(Command(resume=d.model_dump()), cfg)
    save_report(out["report"] | {"status": "completed"})
    update_alert(alert_id, status="completed")
    return out["report"]
