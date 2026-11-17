"""🔍 텔레메트리 인덱스 템플릿과 적재.

이벤트는 날짜별 인덱스(edr-events-2026.11.16)에 들어갑니다. 날짜별로 나누면 오래된 기록을
인덱스째 지울 수 있습니다(보존 기간). 인덱스가 매일 새로 생기므로 매핑은 '템플릿'으로 미리 정해 둡니다.

    python -m soc.telemetry.index_template                         # 템플릿만 만들기
    python -m soc.telemetry.index_template --load data/sim.jsonl   # 템플릿 + 기록 넣기
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from ..config import settings
from ..osclient import bulk_index, get_client

TEMPLATE_NAME = "edr-events"


def build_template() -> dict:
    """edr-events-* 인덱스에 적용할 템플릿."""
    # TODO[REC-1]: 매핑을 채웁니다. 검색·필터에 쓰는 칸(host, type, process.name 등)은 keyword,
    # 시간은 date, pid·ppid·포트·바이트는 long, IP는 ip, 명령줄과 스크립트는 text와 keyword 둘 다(fields 사용).
    # 왜 text와 keyword를 나누는지 DECISIONS.md에 한 줄로 적으세요. (03 문서 1장의 질문)
    properties: dict = {
        # 예: "host": {"type": "keyword"},
    }
    return {
        "index_patterns": [f"{settings.index_events}-*"],
        "template": {
            "settings": {"number_of_shards": 1, "number_of_replicas": 0},   # 노드가 1개라 복제본 0 (2-5 깨 보기)
            "mappings": {"dynamic": "strict", "properties": properties},
        },
    }


def apply_template(client=None) -> None:
    client = client or get_client()
    client.indices.put_index_template(name=TEMPLATE_NAME, body=build_template())


def index_name(ts: str) -> str:
    day = datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%Y.%m.%d")
    return f"{settings.index_events}-{day}"


def load_jsonl(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def index_events(events: list[dict], client=None) -> int:
    """기록을 날짜별 인덱스로 나눠 넣습니다. event_id를 문서 id로 써서 여러 번 넣어도 중복되지 않습니다."""
    client = client or get_client()
    by_index: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        by_index[index_name(e["ts"])].append(e)
    n = sum(bulk_index(client, ix, docs, id_field="event_id") for ix, docs in by_index.items())
    client.indices.refresh(index=f"{settings.index_events}-*")
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", help="넣을 jsonl 파일 (예: data/sim.jsonl)")
    args = ap.parse_args()
    client = get_client()
    apply_template(client)
    print(f"템플릿 '{TEMPLATE_NAME}' 적용 완료")
    if args.load:
        n = index_events(load_jsonl(args.load), client)
        total = client.count(index=f"{settings.index_events}-*")["count"]
        print(f"{n}건 넣음 → 전체 {total}건")


if __name__ == "__main__":
    main()
