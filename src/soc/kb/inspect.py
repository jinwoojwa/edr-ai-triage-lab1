"""📘 9개 PDF를 '그냥' 파싱해 보고, 요소의 종류와 개수를 봅니다. (1일차 3-📘-1)

    python -m soc.kb.inspect --strategy fast
    python -m soc.kb.inspect --strategy fast --file 03 --show 10     # 03번 파일의 요소 10개를 직접 보기
"""
from __future__ import annotations

import argparse
from collections import Counter

from .parse import iter_pdfs, parse_pdf


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="fast", choices=["fast", "hi_res", "ocr_only", "auto"])
    ap.add_argument("--file", help="파일 이름 앞부분 (예: 03)")
    ap.add_argument("--show", type=int, default=0, help="요소를 몇 개 출력할지")
    a = ap.parse_args()
    print(f"{'파일':45s} {'요소 수':>6s}  요소 종류")
    for pdf in iter_pdfs():
        if a.file and not pdf.name.startswith(a.file):
            continue
        els = parse_pdf(pdf, a.strategy)
        kinds = Counter(e.category for e in els).most_common()
        print(f"{pdf.name:45s} {len(els):6d}  {', '.join(f'{k} {v}' for k, v in kinds)}")
        for e in els[: a.show]:
            print(f"    [{e.category}] p.{e.metadata.page_number}: {e.text[:80]!r}")


if __name__ == "__main__":
    main()
