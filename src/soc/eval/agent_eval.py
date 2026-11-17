"""👥 에이전트 평가: 정답 라벨이 있는 시나리오로 에이전트를 돌려 점수를 냅니다.

    python -m soc.eval.agent_eval --n 12

지표
- 판정 정확도   : 악성 시나리오 → malicious, 정상(오탐 유도) 시나리오 → benign 이면 정답. suspicious는 오답으로 셉니다
- 지어낸 근거 비율: 판정이 조회하지 않은 event_id를 인용한 알림의 비율 (가드레일이 잡은 것 포함)
- 승인 요청 비율 : 위험한 조치를 권고해 사람 승인에서 멈춘 비율
- 응답 속도     : 알림 하나를 끝까지 처리한 시간 (평균, 가장 느린 것)
- 알림당 비용   : 토큰 수 × 모델 단가 (.env의 PRICE_IN_PER_1M, PRICE_OUT_PER_1M)

평가는 워커와 따로 돕니다. 알림 대기열에 넣지 않고, 체크포인터도 메모리를 씁니다 (평가가 운영 데이터를 건드리지 않게).
"""
from __future__ import annotations

import argparse
import json
import random
import time
import uuid
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from ..agent.graph import build_graph, run_config
from ..agent.llm import cost_usd
from ..detection.rules import RuleEngine
from ..osclient import get_client
from ..simulator.scenarios import generate_dataset
from ..telemetry.index_template import apply_template, index_events


def labeled_alerts(seed: int = 42):
    events, truths = generate_dataset(seed=seed)
    engine = RuleEngine()
    alerts = [a for e in events for a in engine.process(e)]
    by_event = {eid: t for t in truths for eid in t.event_ids}
    out = []
    for a in alerts:
        t = next((by_event[i] for i in a.event_ids if i in by_event), None)
        if t:
            out.append((a.model_dump(mode="json"), t))
    return events, out


def pick(items, n: int, seed: int):
    """악성과 정상을 섞어 n개 고릅니다 (정상 쪽은 적어도 n/3)."""
    rng = random.Random(seed)
    bad = [x for x in items if x[1].malicious]
    good = [x for x in items if not x[1].malicious]
    rng.shuffle(bad)
    rng.shuffle(good)
    n_good = min(len(good), max(1, n // 3))
    return (good[:n_good] + bad[: n - n_good])[:n]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", help="결과를 JSON으로 저장할 경로")
    a = ap.parse_args()

    events, items = labeled_alerts(a.seed)
    client = get_client()
    apply_template(client)
    index_events([e.model_dump(mode="json", exclude_none=True) for e in events], client)   # 같은 id라 여러 번 넣어도 중복 없음
    chosen = pick(items, a.n, a.seed)
    graph = build_graph(InMemorySaver())
    run_id = uuid.uuid4().hex[:6]
    rows = []
    for alert, truth in chosen:
        cfg = run_config(f"eval-{run_id}-{alert['alert_id']}")
        t0 = time.time()
        out = graph.invoke({"alert": alert}, cfg)
        approval_asked = bool(graph.get_state(cfg).next)
        if approval_asked:
            out = graph.invoke(Command(resume={"approved": True, "approver": "평가"}), cfg)
        sec = time.time() - t0
        r = out["report"]
        expected = "malicious" if truth.malicious else "benign"
        fabricated = any(p.startswith("조회하지 않은 근거") for g in r.get("guardrail_log", []) for p in g.get("problems", []))
        rows.append({"alert_id": alert["alert_id"], "rule_id": alert["rule_id"], "title": alert["title"],
                     "scenario": truth.name, "expected": expected, "verdict": r["verdict"],
                     "correct": r["verdict"] == expected, "fabricated": fabricated, "approval_asked": approval_asked,
                     "sec": round(sec, 2), "cost_usd": cost_usd(r.get("usage", {})), "tokens": r.get("usage", {}),
                     "reasoning": r.get("reasoning"), "trace": r.get("trace")})
        print(f"{'O' if rows[-1]['correct'] else 'X'} {alert['rule_id']} {truth.name:28s} 정답 {expected:9s} 판정 {r['verdict']:10s} {sec:5.1f}초")

    n = len(rows)
    secs = sorted(x["sec"] for x in rows)
    summary = {
        "n": n,
        "판정 정확도": round(sum(x["correct"] for x in rows) / n, 3),
        "지어낸 근거 비율": round(sum(x["fabricated"] for x in rows) / n, 3),
        "승인 요청 비율": round(sum(x["approval_asked"] for x in rows) / n, 3),
        "응답 속도 평균(초)": round(sum(secs) / n, 2),
        "응답 속도 최대(초)": secs[-1],
        "알림당 비용(USD)": round(sum(x["cost_usd"] for x in rows) / n, 5),
    }
    print("\n" + json.dumps(summary, ensure_ascii=False, indent=1))
    wrong = [x for x in rows if not x["correct"]]
    if wrong:
        print("\n틀린 사례 (DECISIONS.md '틀린 사례 분석'에 2개를 골라 원인 단계를 적으세요)")
        for x in wrong:
            print(f"- {x['alert_id']} {x['scenario']}: 정답 {x['expected']}, 판정 {x['verdict']} | {x['reasoning']}")
    if a.out:
        Path(a.out).write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
