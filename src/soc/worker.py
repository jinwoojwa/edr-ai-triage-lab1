"""워커: status=new 알림을 가져가 에이전트를 돌리는 '계속 도는(long-running)' 프로세스.

    python -m soc.worker            # 계속 돌기 (k3s의 worker Deployment)
    python -m soc.worker --once     # 알림 하나만 처리하고 끝 (내 PC에서 확인할 때)

장기 실행에서 챙긴 것
- 하트비트: 루프가 돌 때마다 시각을 남기고, /healthz는 그 시각이 오래됐으면 실패 → liveness가 '멈춘 워커'를 재시작
- 이어 하기: 처리 중에 파드가 죽으면 그 알림은 in_progress로 남습니다. lease가 지나면 다른 워커가 가져가
  체크포인터(Postgres)에 저장된 상태에서 이어 갑니다 (인프라 4-5 깨 보기)
- 우아한 종료: SIGTERM을 받으면 지금 알림을 마치고 끝냅니다 (terminationGracePeriodSeconds)
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from .agent.checkpoint import get_checkpointer
from .agent.graph import build_graph, run_config
from .alerts import claim_next, ensure_indices, save_report, update_alert
from .config import settings

log = logging.getLogger("worker")
WORKER_ID = os.getenv("HOSTNAME") or socket.gethostname()
STATE = {"heartbeat": time.time(), "processed": 0, "failed": 0, "pending_approval": 0, "busy": False}


def pending_request(graph, cfg) -> dict | None:
    """그래프가 사람 승인에서 멈췄으면, 승인권자에게 보여 줄 내용을 돌려줍니다."""
    st = graph.get_state(cfg)
    if not st.next:
        return None
    for task in st.tasks:
        for it in getattr(task, "interrupts", ()) or ():
            return it.value
    return {}


def process(graph, alert: dict) -> str:
    """알림 하나를 처리하고 최종 상태를 돌려줍니다."""
    cfg = run_config(alert["alert_id"])
    resume = alert.get("resumed") and graph.get_state(cfg).next
    if resume:
        log.info("이어서 처리: %s (수첩에 저장된 단계: %s)", alert["alert_id"], graph.get_state(cfg).next)
        out = graph.invoke(None, cfg)                    # 저장된 상태에서 이어 가기
    else:
        out = graph.invoke({"alert": alert}, cfg)
    req = pending_request(graph, cfg)
    if req is not None:
        save_report({"alert_id": alert["alert_id"], "status": "pending_approval", "approval_request": req,
                     "verdict": req.get("verdict")})
        update_alert(alert["alert_id"], status="pending_approval")
        return "pending_approval"
    save_report(out["report"] | {"status": "completed"})
    update_alert(alert["alert_id"], status="completed")
    return "completed"


class _Health(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.startswith("/healthz"):
            age = time.time() - STATE["heartbeat"]
            ok = age < settings.heartbeat_stale_sec
            self._send(200 if ok else 503, f"heartbeat {age:.0f}s ago\n")
        elif self.path.startswith("/metrics"):
            body = "".join(f"soc_worker_{k} {int(v)}\n" for k, v in STATE.items() if k != "heartbeat")
            self._send(200, body)
        else:
            self._send(404, "not found\n")

    def _send(self, code, text):
        self.send_response(code)
        self.send_header("content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(text.encode())

    def log_message(self, *_):
        pass


def serve_health() -> None:
    srv = HTTPServer(("0.0.0.0", settings.health_port), _Health)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log.info("헬스·메트릭: :%d/healthz, /metrics", settings.health_port)


def _print_result(alert_id: str) -> None:
    import json

    from .alerts import get_report

    r = get_report(alert_id) or {}
    keep = ("alert_id", "status", "verdict", "confidence", "techniques", "evidence_event_ids", "sources", "trace",
            "approval_request", "cost_usd")
    print(json.dumps({k: r[k] for k in keep if k in r}, ensure_ascii=False, indent=1))


def run(once: bool = False) -> None:
    stop = {"flag": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(flag=True))
    ensure_indices()
    graph = build_graph(get_checkpointer())
    if not once:
        serve_health()
    log.info("워커 시작: %s", WORKER_ID)
    while not stop["flag"]:
        STATE["heartbeat"] = time.time()
        alert = claim_next(WORKER_ID)
        if not alert:
            if once:
                print("처리할 알림이 없습니다.")
                return
            time.sleep(settings.worker_poll_sec)
            continue
        STATE["busy"] = True
        t = time.time()
        try:
            result = process(graph, alert)
            STATE["processed" if result == "completed" else "pending_approval"] += 1
            log.info("%s %s → %s (%.1f초)", alert["alert_id"], alert.get("title"), result, time.time() - t)
        except Exception as e:  # noqa: BLE001
            STATE["failed"] += 1
            log.exception("처리 실패: %s", alert["alert_id"])
            update_alert(alert["alert_id"], status="failed", error=f"{type(e).__name__}: {e}"[:500])
        finally:
            STATE["busy"] = False
        if once:
            _print_result(alert["alert_id"])
            return
    log.info("SIGTERM: 하던 일을 마치고 종료합니다")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    run(ap.parse_args().once)


if __name__ == "__main__":
    main()
