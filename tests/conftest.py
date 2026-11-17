"""테스트 공통 설정.

- LLM은 항상 가짜(FAKE_LLM), 체크포인터는 메모리 → API 키와 Postgres 없이 돌아갑니다.
- OpenSearch가 켜져 있으면(인프라 0단계 후) 진짜 OpenSearch로, 꺼져 있으면 메모리 흉내로 조사 도구를 시험합니다.
  진짜로 돌려야 keyword/text 매핑 실수(TODO[REC-1])가 드러납니다.
- 테스트용 인덱스 이름(test-…)을 따로 써서 실습 데이터를 건드리지 않습니다.
"""
import os
import urllib.request
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
_env = dotenv_values(ROOT / ".env")
url = os.environ.get("OPENSEARCH_URL") or _env.get("OPENSEARCH_URL") or "http://localhost:9200"


def _reachable(u: str) -> bool:
    try:
        urllib.request.urlopen(u, timeout=1.5)
        return True
    except Exception:  # noqa: BLE001
        return False


os.environ.update({
    "BACKEND": "real" if _reachable(url) else "memory",
    "OPENSEARCH_URL": url,
    "FAKE_LLM": "true",
    "CHECKPOINTER": "memory",
    "TELEMETRY_TOOLS": "mock",
    "KB_TOOLS": "mock",
    "GUARDRAIL_ON_FAIL": "retry",
    "INDEX_EVENTS": "test-edr-events",
    "INDEX_ALERTS": "test-edr-alerts",
    "INDEX_REPORTS": "test-triage-reports",
})
print(f"\n[conftest] 조사 도구 테스트 대상: {'진짜 OpenSearch ' + url if os.environ['BACKEND'] == 'real' else '메모리 흉내 (OpenSearch 꺼짐)'}")
