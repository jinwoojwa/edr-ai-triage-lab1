"""가상 회사의 PC 활동 기록을 만들고, 탐지 룰로 알림을 만드는 생성기.

    python -m soc.simulator.run --dump data/sim.jsonl          # 데이터셋 파일로 저장 (항상 같은 결과, 정답 라벨 포함)
    python -m soc.simulator.run --load                         # 데이터셋을 OpenSearch에 넣고 알림까지 만들기
    python -m soc.simulator.run --inject credential_dump --host WS-007   # 공격 하나를 '지금' 시각으로 주입
    python -m soc.simulator.run --loop                         # 계속 생성 (k3s의 generator Deployment)

정답 라벨(--dump 시 data/sim_labels.jsonl): 시나리오 이름, 악성 여부, ATT&CK 기법, 관련 event_id
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import signal
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..alerts import ensure_indices, save_alert
from ..config import settings
from ..detection.rules import RuleEngine
from ..osclient import get_client
from ..schema import Event
from ..telemetry.index_template import apply_template, index_events
from .scenarios import ATTACKS, FP_BAITS, HOSTS, benign_burst, generate_dataset, reset_ids

log = logging.getLogger("generator")
SCENARIOS = {f.__name__: f for f in ATTACKS + FP_BAITS}


def _dump(e: Event) -> dict:
    return e.model_dump(mode="json", exclude_none=True)


def detect(events: list[Event], engine: RuleEngine | None = None):
    engine = engine or RuleEngine()
    return [a for e in sorted(events, key=lambda x: x.ts) for a in engine.process(e)]


def push(events: list[Event], engine: RuleEngine | None = None, client=None) -> tuple[int, int]:
    """기록을 넣고 → 탐지 → 알림 저장. 순서가 중요합니다: 기록이 먼저 있어야 에이전트가 조사할 수 있습니다."""
    client = client or get_client()
    index_events([_dump(e) for e in events], client)
    alerts = detect(events, engine)
    saved = sum(save_alert(a, client) for a in alerts)
    return len(events), saved


def write_dataset(path: str, seed: int = 42) -> None:
    events, truths = generate_dataset(seed=seed)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(_dump(e), ensure_ascii=False) + "\n")
    labels = p.with_name(p.stem + "_labels.jsonl")
    with labels.open("w", encoding="utf-8") as f:
        for t in truths:
            f.write(json.dumps({"scenario_id": t.scenario_id, "name": t.name, "host": t.host,
                                "malicious": t.malicious, "techniques": t.techniques,
                                "event_ids": t.event_ids}, ensure_ascii=False) + "\n")
    print(f"기록 {len(events)}건 → {p}\n정답 라벨 {len(truths)}건 → {labels}")


def _shift_to_now(events: list[Event]) -> list[Event]:
    """시나리오의 상대 시간 간격은 유지하고, 시작 시각을 '지금'으로 옮깁니다."""
    if not events:
        return events
    base, now = min(e.ts for e in events), datetime.now(timezone.utc)
    for e in events:
        e.ts = now + (e.ts - base)
    return events


def inject(name: str, host: str) -> None:
    reset_ids(1, prefix=f"evt-{uuid.uuid4().hex[:6]}")
    events, gt = SCENARIOS[name](host, datetime.now(timezone.utc), random.Random())
    _shift_to_now(events)
    client = get_client()
    apply_template(client)
    ensure_indices(client)
    n, saved = push(events, client=client)
    print(f"'{name}'을 {host}에 주입: 기록 {n}건, 새 알림 {saved}건 (악성: {gt.malicious})")


def loop() -> None:
    """generator Deployment: 정상 활동을 계속 만들고, 가끔 공격이나 오탐 유도 상황을 섞습니다."""
    stop = {"flag": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(flag=True))
    client, rng, engine = get_client(), random.Random(), RuleEngine()
    apply_template(client)
    ensure_indices(client)
    reset_ids(1, prefix=f"evt-{uuid.uuid4().hex[:6]}")
    tick = 0
    while not stop["flag"]:
        tick += 1
        now = datetime.now(timezone.utc)
        events: list[Event] = []
        for _ in range(settings.sim_benign_per_tick):
            events += benign_burst(rng.choice(HOSTS[:10]), now, rng)
        if tick % settings.sim_attack_every_ticks == 0:
            fn = rng.choice(ATTACKS + FP_BAITS)
            evs, _ = fn(rng.choice(HOSTS[:10]), now, rng)
            events += evs
            log.info("시나리오 주입: %s", fn.__name__)
        n, saved = push(events, engine, client)
        log.info("기록 %d건, 새 알림 %d건", n, saved)
        time.sleep(settings.sim_tick_sec)


def load_dataset(path: str | None, seed: int) -> None:
    client = get_client()
    apply_template(client)
    ensure_indices(client)
    if path:
        from ..telemetry.index_template import load_jsonl

        events = [Event.model_validate(d) for d in load_jsonl(path)]
    else:
        events, _ = generate_dataset(seed=seed)
    n, saved = push(events, client=client)
    print(f"기록 {n}건을 넣고, 새 알림 {saved}건을 만들었습니다.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dump", metavar="PATH")
    g.add_argument("--load", nargs="?", const="", metavar="PATH", help="파일을 주지 않으면 데이터셋을 새로 만들어 넣음")
    g.add_argument("--inject", choices=sorted(SCENARIOS))
    g.add_argument("--loop", action="store_true")
    ap.add_argument("--host", default="WS-007")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    if a.dump:
        write_dataset(a.dump, a.seed)
    elif a.load is not None:
        load_dataset(a.load or None, a.seed)
    elif a.inject:
        inject(a.inject, a.host)
    else:
        loop()


if __name__ == "__main__":
    main()
