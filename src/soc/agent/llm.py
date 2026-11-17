"""LLM 선택: OpenAI 또는 가짜 LLM(FAKE_LLM=true, API 키 없이 흐름 확인용)."""
from __future__ import annotations

from functools import lru_cache

from ..config import settings


@lru_cache(maxsize=1)
def get_llm():
    if settings.fake_llm:
        from .fake_llm import FakeLLM

        return FakeLLM()
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=settings.chat_model, api_key=settings.openai_api_key, temperature=0, timeout=60)


def usage_of(msg) -> dict:
    u = getattr(msg, "usage_metadata", None) or {}
    return {"input_tokens": u.get("input_tokens", 0), "output_tokens": u.get("output_tokens", 0), "llm_calls": 1}


def cost_usd(usage: dict) -> float:
    return round(usage.get("input_tokens", 0) / 1e6 * settings.price_in_per_1m
                 + usage.get("output_tokens", 0) / 1e6 * settings.price_out_per_1m, 6)
