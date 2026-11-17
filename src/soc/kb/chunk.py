"""📘 2단계 청킹: 요소들을 검색 단위(청크)로 묶고, OpenSearch에 넣을 레코드로 바꿉니다.

chunk_by_title: 제목(Title)이 나오면 새 청크를 시작하고, 길이 제한 안에서 요소를 이어 붙입니다.
- max_characters    : 청크의 최대 길이 (넘으면 무조건 자름)
- new_after_n_chars : 이 길이를 넘으면 다음 제목 전이라도 새 청크를 시작 (부드러운 제한)
"""
from __future__ import annotations

import hashlib
from itertools import groupby

from ..config import settings


def make_chunks(elements: list, max_characters: int | None = None, new_after_n_chars: int | None = None) -> list:
    from unstructured.chunking.title import chunk_by_title

    max_characters = max_characters or settings.chunk_max_characters
    new_after_n_chars = new_after_n_chars or min(settings.chunk_new_after_n_chars, max_characters)
    chunks = []
    # A record has one page number, so do not combine text from different pages.
    for _, page_elements in groupby(elements, key=lambda element: element.metadata.page_number):
        chunks.extend(
            chunk_by_title(
                list(page_elements),
                max_characters=max_characters,
                new_after_n_chars=new_after_n_chars,
            )
        )
    return chunks


def to_records(chunks: list, source: str) -> list[dict]:
    """청크 → 저장할 레코드. 출처 정보(source, page, category, text_as_html)를 남깁니다. (이미 만들어 둔 도우미)"""
    out = []
    for i, ch in enumerate(chunks):
        text = (ch.text or "").strip()
        if not text:
            continue
        md = ch.metadata
        out.append({
            # 같은 파일·같은 순번이면 같은 id → 다시 적재해도 중복이 생기지 않음
            "id": hashlib.sha1(f"{source}:{i}".encode()).hexdigest()[:16],
            "text": text,
            "source": source,
            "page": md.page_number,
            "category": ch.category,
            "chunk_index": i,
            "text_as_html": getattr(md, "text_as_html", None),
        })
    return out
