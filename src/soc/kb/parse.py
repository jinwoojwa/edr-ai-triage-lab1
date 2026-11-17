"""📘 1단계 파싱: PDF를 Unstructured '요소(Element)' 목록으로 바꿉니다.

요소 = Title, NarrativeText, ListItem, Table, Header, Footer … 처럼 '종류(category)'가 붙은 글 조각.
파싱 방법(strategy)
- fast     : PDF 안의 글자 층을 그대로 읽음. 빠르지만 표 구조와 스캔본은 못 읽음
- hi_res   : 레이아웃 모델로 페이지를 봄. 표 구조(text_as_html)를 얻을 수 있음. 느리고 첫 실행 때 모델을 내려받음
- ocr_only : 이미지에서 글자를 인식 (스캔본용, Tesseract 필요)
"""
from __future__ import annotations

from pathlib import Path

from ..config import settings


def iter_pdfs(root: str | Path | None = None):
    for p in sorted(Path(root or settings.kb_pdf_dir).glob("*.pdf")):
        yield p


def parse_pdf(path: str | Path, strategy: str | None = None) -> list:
    """PDF 하나를 요소 목록으로."""
    from unstructured.partition.auto import partition

    strategy = strategy or settings.parse_strategy
    # TODO[DOC-1]: partition()을 호출합니다. 파싱 방법은 strategy 변수로 받고,
    # 언어는 한국어와 영어(languages), 표 구조 추출(infer_table_structure)을 켭니다.
    raise NotImplementedError("TODO[DOC-1]")


def drop_header_footer(elements: list) -> list:
    """페이지마다 반복되는 머리말·꼬리말("대외비" 등)을 걸러냅니다. 03번 PDF로 확인하세요."""
    # TODO[DOC-2]: category가 Header, Footer인 요소를 뺀 목록을 돌려줍니다.
    # 같은 글이 여러 페이지에 반복되는데 Header/Footer로 분류되지 않는 경우도 있습니다. 결과를 눈으로 확인하세요.
    raise NotImplementedError("TODO[DOC-2]")
