"""📘 3단계 임베딩: 글을 벡터(숫자 목록)로 바꿉니다. 여러 개를 한 번에 보내 API 호출 수를 줄입니다.

FAKE_LLM=true면 API 키 없이 글자 조각으로 만든 가짜 벡터를 씁니다 (흐름 확인용, 의미 검색은 안 됨).
"""
from __future__ import annotations

import hashlib
import math
from functools import lru_cache

from ..config import settings

BATCH = 64


@lru_cache(maxsize=1)
def _client():
    from openai import OpenAI

    return OpenAI(api_key=settings.openai_api_key)


def _fake_vector(text: str) -> list[float]:
    v = [0.0] * settings.embed_dim
    for i in range(len(text) - 1):
        h = int(hashlib.md5(text[i:i + 2].encode()).hexdigest(), 16)
        v[h % settings.embed_dim] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def embed_texts(texts: list[str]) -> list[list[float]]:
    if settings.fake_llm:
        return [_fake_vector(t) for t in texts]
    out: list[list[float]] = []
    for i in range(0, len(texts), BATCH):
        resp = _client().embeddings.create(model=settings.embed_model, input=texts[i:i + BATCH])
        out.extend(d.embedding for d in resp.data)
    return out


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]
