"""체크포인터: 에이전트 상태를 저장하는 곳 (01b 문서의 '경비원의 수첩'). 2일차 1-3, 운전 🔍

- memory  : 프로세스 안의 메모리. 프로세스가 끝나면 사라짐
- postgres: Postgres 테이블. 파드가 바뀌어도 남음 → 승인 후 이어 가기, 처리 중 워커가 죽어도 이어 가기
"""
from __future__ import annotations

import atexit
import logging
from functools import lru_cache

from langgraph.checkpoint.memory import InMemorySaver

from ..config import settings

log = logging.getLogger("checkpoint")
_pools = []


def _kind() -> str:
    if settings.checkpointer != "auto":
        return settings.checkpointer
    return "postgres" if settings.backend == "real" else "memory"


@lru_cache(maxsize=1)
def get_checkpointer():
    if _kind() == "memory":
        return InMemorySaver()
    if _kind() != "postgres":
        raise ValueError(f"지원하지 않는 체크포인터: {_kind()}")

    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    pool = ConnectionPool(
        conninfo=settings.postgres_dsn,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row,
                "connect_timeout": 3},
        min_size=1,
        max_size=10,
        open=False,
    )
    try:
        pool.open(wait=True, timeout=15)
        saver = PostgresSaver(pool)
        saver.setup()
    except Exception:
        pool.close()
        raise
    _pools.append(pool)
    log.info("Postgres 체크포인터 준비 완료")
    return saver


def close_checkpointer() -> None:
    """프로세스 종료 또는 테스트 재설정 때 연결 풀을 닫습니다."""
    get_checkpointer.cache_clear()
    while _pools:
        _pools.pop().close()


atexit.register(close_checkpointer)


def ping() -> bool:
    """/readyz에서 씀: Postgres에 연결되는가."""
    if _kind() == "memory":
        return True
    try:
        import psycopg

        with psycopg.connect(settings.postgres_dsn, connect_timeout=3) as c:
            c.execute("select 1")
        return True
    except Exception:  # noqa: BLE001
        return False
