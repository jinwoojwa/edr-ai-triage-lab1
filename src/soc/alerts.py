"""알림과 리포트 저장소.

카프카 대신 OpenSearch의 `status` 칸이 대기열 역할을 합니다.

    new ──(워커가 가져감)──► in_progress ──► completed
                                  │   └────► failed
                                  └──(위험한 조치)──► pending_approval ──(사람 승인)──► completed

여러 워커가 같은 알림을 동시에 가져가지 않도록 '낙관적 잠금'을 씁니다.
읽을 때의 버전(_seq_no)과 지금 버전이 다르면 갱신이 거절됩니다 → 다른 워커가 먼저 가져간 것.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from .config import settings
from .osclient import get_client, is_conflict, is_not_found
from .schema import Alert

log = logging.getLogger("alerts")

ALERT_MAPPING = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {"properties": {
        "alert_id": {"type": "keyword"}, "ts": {"type": "date"}, "host": {"type": "keyword"},
        "source": {"type": "keyword"}, "rule_id": {"type": "keyword"}, "title": {"type": "text"},
        "severity": {"type": "keyword"}, "techniques": {"type": "keyword"}, "event_ids": {"type": "keyword"},
        "pid": {"type": "long"}, "score": {"type": "float"},
        "status": {"type": "keyword"}, "worker": {"type": "keyword"}, "attempts": {"type": "integer"},
        "created_at": {"type": "date"}, "updated_at": {"type": "date"}, "lease_until": {"type": "date"},
        "error": {"type": "text"},
    }},
}
REPORT_MAPPING = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {"dynamic": True, "properties": {
        "alert_id": {"type": "keyword"}, "verdict": {"type": "keyword"}, "created_at": {"type": "date"},
    }},
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def ensure_indices(client=None) -> None:
    """알림·리포트 인덱스를 만듭니다. 이미 있으면 그대로 둡니다 (여러 번 실행해도 안전 = 멱등)."""
    client = client or get_client()
    for name, body in ((settings.index_alerts, ALERT_MAPPING), (settings.index_reports, REPORT_MAPPING)):
        if not client.indices.exists(index=name):
            client.indices.create(index=name, body=body)


def save_alert(alert: Alert, client=None) -> bool:
    """새 알림을 status=new로 저장. 같은 알림 id가 이미 있으면 덮어쓰지 않습니다."""
    client = client or get_client()
    try:
        client.get(index=settings.index_alerts, id=alert.alert_id)
        return False
    except Exception as e:  # noqa: BLE001
        if not is_not_found(e):
            raise
    doc = alert.model_dump(mode="json") | {"status": "new", "attempts": 0,
                                           "created_at": _iso(_now()), "updated_at": _iso(_now())}
    client.index(index=settings.index_alerts, id=alert.alert_id, body=doc, refresh=True)
    return True


def get_alert(alert_id: str, client=None) -> dict | None:
    client = client or get_client()
    try:
        return client.get(index=settings.index_alerts, id=alert_id)["_source"]
    except Exception as e:  # noqa: BLE001
        if is_not_found(e):
            return None
        raise


def list_alerts(status: str | None = None, size: int = 50, client=None) -> list[dict]:
    client = client or get_client()
    q = {"term": {"status": status}} if status else {"match_all": {}}
    res = client.search(index=settings.index_alerts, body={"query": q, "size": size, "sort": [{"created_at": "desc"}]})
    return [h["_source"] for h in res["hits"]["hits"]]


def count_by_status(client=None) -> dict[str, int]:
    client = client or get_client()
    from .schema import ALERT_STATUSES

    return {s: client.count(index=settings.index_alerts, body={"query": {"term": {"status": s}}})["count"]
            for s in ALERT_STATUSES}


def update_alert(alert_id: str, client=None, **fields) -> None:
    client = client or get_client()
    client.update(index=settings.index_alerts, id=alert_id,
                  body={"doc": fields | {"updated_at": _iso(_now())}}, refresh=True)


def claim_next(worker_id: str, client=None) -> dict | None:
    """처리할 알림 하나를 가져옵니다.

    1순위: 다른 워커가 처리하다 멈춘 알림 (in_progress인데 lease가 지남) → 수첩(체크포인트)으로 이어서
    2순위: 새 알림 (new), 심각도가 높고 오래된 것부터
    """
    client = client or get_client()
    now = _iso(_now())
    queries = [
        {"bool": {"filter": [{"term": {"status": "in_progress"}}, {"range": {"lease_until": {"lt": now}}}]}},
        {"term": {"status": "new"}},
    ]
    for q in queries:
        res = client.search(index=settings.index_alerts,
                            body={"query": q, "size": 5, "sort": [{"created_at": "asc"}]}, seq_no_primary_term=True)
        for h in res["hits"]["hits"]:
            src = h["_source"]
            try:
                client.update(index=settings.index_alerts, id=h["_id"], if_seq_no=h["_seq_no"],
                              if_primary_term=h["_primary_term"], refresh=True,
                              body={"doc": {"status": "in_progress", "worker": worker_id,
                                            "attempts": src.get("attempts", 0) + 1,
                                            "lease_until": _iso(_now() + timedelta(seconds=settings.worker_lease_sec)),
                                            "updated_at": now}})
                src["resumed"] = src.get("status") == "in_progress"
                return src
            except Exception as e:  # noqa: BLE001
                if is_conflict(e):
                    continue          # 다른 워커가 먼저 가져감
                raise
    return None


def save_report(report: dict, client=None) -> None:
    client = client or get_client()
    client.index(index=settings.index_reports, id=report["alert_id"],
                 body=report | {"created_at": _iso(_now())}, refresh=True)


def get_report(alert_id: str, client=None) -> dict | None:
    client = client or get_client()
    try:
        return client.get(index=settings.index_reports, id=alert_id)["_source"]
    except Exception as e:  # noqa: BLE001
        if is_not_found(e):
            return None
        raise
