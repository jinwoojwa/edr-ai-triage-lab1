# 코드 안내: 어디에 무엇이 있고, 어떻게 돌리나

## 1. 처음 한 번: 개발 환경

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt          # 앱 (둘 다)
pip install -r requirements-kb.txt       # 📘 문서 담당: PDF 파싱(Unstructured)까지
pip install -e .                         # 둘 다: `python -m soc.…` 명령이 어디서든 soc 패키지를 찾게 (src/ 아래에 있어서 필요)
cp .env.example .env                     # Windows: copy .env.example .env  → OPENAI_API_KEY 채우기
pytest -q                                # 아직 TODO가 있어 실패가 많은 게 정상입니다
```

- 설정은 모두 `.env`에서 읽습니다. k3s에서는 같은 이름의 값이 ConfigMap·Secret으로 들어갑니다.
- **LangSmith**(선택): `.env`에 `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`를 넣으면, 에이전트가 어떤 도구를 몇 번 불렀고 단계마다 얼마나 걸렸는지 smith.langchain.com에서 볼 수 있습니다. 코드는 바꾸지 않아도 됩니다.
- API 키 없이 흐름만 보고 싶으면 `.env`에 `FAKE_LLM=true`.

## 2. 폴더 지도

| 위치 | 내용 | 주인 |
|---|---|---|
| `src/soc/mocks.py` | 가짜 도구 4개 (도구 계약의 견본) | 👥 1일차 계약 |
| `src/soc/telemetry/index_template.py` | 텔레메트리 인덱스 템플릿, 기록 넣기 | 🔍 REC-1 |
| `src/soc/telemetry/tools.py` | 조사 도구 3개 | 🔍 REC-2~4 |
| `src/soc/kb/inspect.py` | 9개 PDF를 그냥 파싱해 보기 | 📘 |
| `src/soc/kb/parse.py`, `chunk.py` | 파싱, 머리말·꼬리말 제거, 청킹 | 📘 DOC-1~3 |
| `src/soc/kb/index.py`, `search.py` | 인덱스 매핑, 키워드+벡터+RRF 검색 | 📘 DOC-4~5 |
| `src/soc/kb/ingest.py` | PDF 적재 파이프라인 | 📘 |
| `src/soc/agent/graph.py`, `nodes.py` | 에이전트 그래프와 노드 | 👥 AG-1~3 |
| `src/soc/agent/guardrail.py` | 가드레일 | 👥 G-1~2 (운전 📘) |
| `src/soc/agent/nodes.py` 승인, `checkpoint.py` | 사람 승인, 상태 저장 | 👥 H-1~2 (운전 🔍) |
| `src/soc/api/dify.py` | Dify 연결 | 👥 DIFY-1 |
| `src/soc/simulator/`, `detection/` | 가상 PC 기록 생성, 탐지 룰 (제공) | |
| `src/soc/alerts.py`, `worker.py`, `api/main.py` | 알림 대기열, 워커, API (제공) | |
| `src/soc/eval/` | RAG 평가, 에이전트 평가 (제공) | |
| `tests/` | TODO마다 확인하는 테스트 | |

코드에서 `# TODO[번호]`를 찾으면 채울 곳과 힌트가 있습니다. 나머지 코드는 동작하도록 만들어 두었습니다.

## 3. 자주 쓰는 명령

| 언제 | 명령 |
|---|---|
| 1일차 🔍 | `python -m soc.simulator.run --dump data/sim.jsonl` (데이터셋 + 정답 라벨 만들기) |
| 1일차 🔍 | `python -m soc.telemetry.index_template --load data/sim.jsonl` (템플릿 적용 + 기록 넣기) |
| 1일차 🔍 | `pytest tests/test_telemetry_tools.py -q` |
| 1일차 📘 | `python -m soc.kb.inspect --strategy fast` / `python -m soc.kb.ingest --dry-run` / `python -m soc.kb.ingest` |
| 1일차 📘 | `python -m soc.eval.rag_eval --mode all` (키워드만 / 벡터만 / 합친 것) |
| 1일차 👥 | `pytest tests/test_graph_skeleton.py -q` / `python -m soc.agent.graph` (Mermaid 그림) |
| 2일차 | `python -m soc.simulator.run --inject credential_dump --host WS-007` (01 문서의 예시 알림 주입) |
| 2일차 | `python -m soc.worker --once` (알림 하나를 에이전트로 처리하고 결과 출력) |
| 2일차 | `uvicorn soc.api.main:app --port 8000` → http://localhost:8000/docs 에서 `POST /approvals/{alert_id}` |
| 2일차 | `pytest tests/test_guardrail.py tests/test_approval.py -q` |
| 2일차 | `python -m soc.eval.rag_eval` / `python -m soc.eval.agent_eval --n 12` (기준점) |
| 2일차 교차 | `python -m soc.kb.ingest --max-characters 500` → `python -m soc.eval.rag_eval` |
| 언제든 | `python -m soc.simulator.run --load` (데이터셋 전체를 넣고 알림 22개 만들기) |

## 4. 에이전트가 알림 하나를 처리하는 길

```
생성기(simulator --loop) ─기록→ OpenSearch edr-events-*  ─탐지 룰→ edr-alerts (status=new)
                                                                     │
워커(soc.worker) ── 가져감(in_progress) ── 조사 ⇄ 도구 → 판정 → 가드레일 → 권고 → 승인 → 리포트
                                                                                │ 위험한 조치면 멈춤
                                                     status=pending_approval ◄──┘ (상태는 Postgres에)
API  POST /approvals/{id} ── 승인/거절 → 멈춘 곳부터 이어서 → triage-reports, status=completed
```

## 5. .env의 스위치

| 값 | 뜻 | 바꾸는 때 |
|---|---|---|
| `BACKEND` | memory: 인프라 없이 / real: OpenSearch·Postgres | 인프라 0단계 뒤 real |
| `TELEMETRY_TOOLS`, `KB_TOOLS` | mock / real | 2일차 1-1에서 완성된 쪽부터 real |
| `GUARDRAIL_ON_FAIL` | retry / downgrade | 2일차 1-2에서 둘이 정함 |
| `CHECKPOINTER` | auto / memory / postgres | 2일차 1-3 실험 (API를 껐다 켜도 승인 후 이어지나?) |
| `FAKE_LLM` | true면 API 키 없이 가짜 LLM | 흐름만 볼 때 |
| `LANGSMITH_TRACING` | true면 LangSmith로 추적 전송 | 언제든 |
