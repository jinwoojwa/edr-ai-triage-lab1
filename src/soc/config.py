"""모든 컴포넌트가 함께 쓰는 설정.

- 내 PC: 프로젝트 맨 위의 `.env` 파일에서 읽습니다 (`.env.example`을 복사해서 만듭니다).
- k3s: ConfigMap과 Secret이 같은 이름의 환경변수로 넣어 줍니다. 코드는 바꾸지 않습니다.

LangSmith 추적: `.env`에 LANGSMITH_TRACING=true, LANGSMITH_API_KEY를 넣으면
LangChain/LangGraph가 환경변수를 보고 자동으로 추적을 보냅니다. 그래서 `.env`를 os.environ에도 올립니다.
"""
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), extra="ignore")

    # 실행 모드 ------------------------------------------------------------
    # memory : OpenSearch·Postgres 없이 메모리에서 (인프라 1단계, 빠른 테스트)
    # real   : OpenSearch + Postgres (인프라 0단계 이후)
    backend: str = "memory"

    # 에이전트가 쓸 도구: real(직접 만든 것) / mock(mocks.py의 가짜). 2일차 1-1에서 하나씩 real로 바꿉니다.
    telemetry_tools: str = "mock"
    kb_tools: str = "mock"

    # OpenSearch -----------------------------------------------------------
    opensearch_url: str = "http://localhost:9200"
    index_events: str = "edr-events"          # 실제 인덱스는 edr-events-YYYY.MM.DD (템플릿: edr-events-*)
    index_alerts: str = "edr-alerts"
    index_reports: str = "triage-reports"
    index_kb: str = "kb-playbooks"

    # Postgres (에이전트 상태 저장 = 경비원의 수첩) --------------------------
    postgres_dsn: str = "postgresql://soc:soc@localhost:5432/soc"

    # LLM -------------------------------------------------------------------
    fake_llm: bool = False                  # true: API 키 없이 규칙으로 흉내 내는 가짜 LLM
    openai_api_key: str = ""
    chat_model: str = "gpt-4o-mini"
    embed_model: str = "text-embedding-3-small"
    embed_dim: int = 1536
    price_in_per_1m: float = 0.15           # 비용 계산용 (USD / 입력 토큰 100만 개)
    price_out_per_1m: float = 0.60

    # 에이전트 예산 ------------------------------------------------------------
    max_tool_rounds: int = 6                # 조사 단계에서 도구를 부르는 최대 횟수
    # 가드레일이 실패하면? (2일차 1-2에서 둘이 정합니다)
    #   retry     : 부족한 점을 알려 주고 한 번 더 조사 → 그래도 실패하면 '의심'으로 낮춤
    #   downgrade : 바로 '의심'으로 낮추고 사람 검토 표시
    guardrail_on_fail: str = "retry"
    max_guardrail_retries: int = 1

    # 상태 저장(체크포인터): auto = BACKEND가 real이면 postgres, memory면 memory
    checkpointer: str = "auto"

    # 워커 ------------------------------------------------------------------
    worker_poll_sec: float = 2.0
    worker_lease_sec: int = 300             # in_progress가 이보다 오래 갱신되지 않으면 다른 워커가 이어 받음
    heartbeat_stale_sec: int = 60           # 하트비트가 이보다 오래되면 /healthz 실패
    health_port: int = 9100

    # 생성기 -----------------------------------------------------------------
    sim_benign_per_tick: int = 5
    sim_tick_sec: float = 5.0
    sim_attack_every_ticks: int = 24

    # KB ---------------------------------------------------------------------
    kb_pdf_dir: str = str(ROOT / "data" / "kb" / "pdf")
    parse_strategy: str = "fast"            # fast / hi_res / ocr_only
    chunk_max_characters: int = 800
    chunk_new_after_n_chars: int = 600

    # 연동 -------------------------------------------------------------------
    triage_api_key: SecretStr = SecretStr("")  # 유료 트리아지 전용. 비어 있으면 해당 API만 차단
    dify_api_key: str = "change-me"
    prompt_version: str = "v1"


settings = Settings()
