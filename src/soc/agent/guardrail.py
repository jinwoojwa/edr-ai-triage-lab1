"""가드레일: LLM의 판정을 그대로 믿지 않고 기계적으로 검증합니다. (2일차 1-2, 운전 📘)

01 문서 4장의 '근거 추적'과 01번 정책 PDF 3장의 판정 기준을 코드로 옮긴 것입니다.

    pytest tests/test_guardrail.py -q
"""
from __future__ import annotations


def check_evidence_exists(verdict: dict, seen_event_ids: list[str], alert: dict) -> list[str]:
    """판정이 인용한 event_id가 도구로 실제 조회한 기록 안에 있는지 확인합니다.

    알림 자체의 event_ids(탐지 룰이 붙인 근거)도 확인된 기록으로 칩니다.
    돌려주는 것: 문제 설명 목록 (문제가 없으면 빈 목록)
    """
    # TODO[G-1]: verdict["evidence_event_ids"] 중 seen_event_ids에도, alert["event_ids"]에도 없는 id를 찾아
    # "조회하지 않은 근거: evt-..." 같은 문제 설명으로 돌려줍니다.
    return []


def check_malicious_needs_two(verdict: dict) -> list[str]:
    """악성 판정에는 서로 다른 근거가 2개 이상 있어야 합니다. (01번 정책 PDF 3장 판정 기준)"""
    # TODO[G-2]: verdict가 "malicious"인데 서로 다른 근거 id가 2개 미만이면 문제 설명을 돌려줍니다.
    return []


def check(verdict: dict, seen_event_ids: list[str], alert: dict) -> dict:
    problems = check_evidence_exists(verdict, seen_event_ids, alert) + check_malicious_needs_two(verdict)
    return {"ok": not problems, "problems": problems}
