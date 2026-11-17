"""📘 RAG 평가: 정답 문서가 검색 상위 3개 안에 드는 비율(Recall@3).

    python -m soc.eval.rag_eval                  # 하이브리드(기본)
    python -m soc.eval.rag_eval --mode all       # 키워드만 / 벡터만 / 하이브리드 비교 (1일차 3-📘-4)
    python -m soc.eval.rag_eval --k 1            # Recall@1

질문 세트: data/kb/eval_questions.jsonl (21문항, 질문·정답 문서·어려운 점)
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from ..config import ROOT
from ..kb.search import search

QUESTIONS = ROOT / "data" / "kb" / "eval_questions.jsonl"


def load_questions(path: Path = QUESTIONS) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def evaluate(mode: str, k: int, questions: list[dict]) -> dict:
    rows = []
    for q in questions:
        hits = search(q["question"], k, mode=mode)
        sources = [h["source"] for h in hits]
        rows.append({"id": q["id"], "hit": q["source"] in sources, "expected": q["source"], "got": sources,
                     "challenge": q.get("challenge", "")})
    return {"mode": mode, "k": k, "recall": sum(r["hit"] for r in rows) / len(rows), "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="hybrid", choices=["hybrid", "keyword", "vector", "all"])
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--out", help="결과를 JSON으로 저장할 경로")
    a = ap.parse_args()
    qs = load_questions()
    modes = ["keyword", "vector", "hybrid"] if a.mode == "all" else [a.mode]
    results = [evaluate(m, a.k, qs) for m in modes]

    print(f"\n{'문항':5s} " + " ".join(f"{m:>8s}" for m in modes) + "  정답 문서 / 어려운 점")
    for i, q in enumerate(qs):
        marks = " ".join(f"{'O' if r['rows'][i]['hit'] else '.':>8s}" for r in results)
        print(f"{q['id']:5s} {marks}  {q['source'][:28]} / {q.get('challenge', '')}")
    print()
    for r in results:
        by = defaultdict(list)
        for row in r["rows"]:
            by[row["expected"][:2]].append(row["hit"])
        per_doc = " ".join(f"{d}:{sum(v)}/{len(v)}" for d, v in sorted(by.items()))
        print(f"{r['mode']:8s} Recall@{a.k} = {r['recall']:.3f}   문서별 {per_doc}")
    if a.out:
        Path(a.out).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
