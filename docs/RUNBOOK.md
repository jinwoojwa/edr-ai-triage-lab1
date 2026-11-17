# 런북: 우리가 겪은 장애와 찾는 법

> 02 문서 8장의 **'좋은 런북'** 형식으로 씁니다. 새벽 당번이 이것만 보고 해결할 수 있게, **실제로 친 명령과 실제 출력**을 남깁니다.

## 로컬 인프라 0단계: 팀 Compose

현재 `docker-compose.yml`은 OpenSearch **2.19.0**(호스트 9200), Dashboards **2.19.0**(호스트 5601), PostgreSQL **16**(호스트 5432)을 띄운다. 선택 프로필 `app`은 API(호스트 8000)를 빌드해 추가한다. 호스트에서 실행하는 Python은 기존 `.env`의 `OPENSEARCH_URL=http://localhost:9200`과 `POSTGRES_DSN=postgresql://soc:soc@localhost:5432/soc`을 쓴다. 컨테이너 안의 API는 서비스 이름 `opensearch`, `postgres`로 접속한다. 모든 호스트 포트는 `127.0.0.1`에만 연결한다. 실습용 OpenSearch 보안 플러그인은 꺼져 있다.

이 PC에는 이전 3.9.0 Compose의 `edr-ai-triage-lab1_opensearch-data` 볼륨이 남아 있다. 2.19.0을 그 볼륨에 연결하지 않도록 아래 명령은 별도 프로젝트 이름 `edr-ai-triage-lab1-team`을 사용한다. 이 PC에서 `-p`를 빼면 이전 프로젝트의 볼륨을 다시 사용할 수 있으므로 같은 이름을 유지한다. 다른 PC에서도 5601 포트가 이미 사용 중이면 충돌 원인을 확인한 뒤 로컬에서만 포트를 조정한다.

현재 `.env`에는 `POSTGRES_DSN`의 암호 `soc`가 있지만 Compose가 요구하는 `POSTGRES_PASSWORD` 변수는 없다. **새 PowerShell 창마다** 다음처럼 두 값을 맞춰 설정한 뒤 실행한다. `POSTGRES_PASSWORD`를 `.env`에 추가하기 전까지는 이 설정이 필요하다.

```powershell
$env:POSTGRES_PASSWORD='soc'
docker compose -p edr-ai-triage-lab1-team config --quiet
docker compose -p edr-ai-triage-lab1-team --profile app up -d --build --quiet-pull
docker compose -p edr-ai-triage-lab1-team ps
```

API 없이 인프라 3개만 띄울 때는 `docker compose -p edr-ai-triage-lab1-team up -d --quiet-pull`을 쓴다. 상태와 접속 확인:

```powershell
Invoke-RestMethod http://localhost:9200/_cluster/health | Select-Object cluster_name, status, number_of_nodes
Invoke-WebRequest http://localhost:5601/ -UseBasicParsing | Select-Object StatusCode
docker compose -p edr-ai-triage-lab1-team exec -T postgres psql -U soc -d soc -Atqc 'select 1'
Invoke-RestMethod http://localhost:8000/healthz
Invoke-RestMethod http://localhost:8000/readyz
```

OpenSearch가 `green` 또는 `yellow`이고 노드가 1개, Dashboards HTTP가 200, SQL 결과가 `1`, API의 `ready`, `opensearch`, `postgres`가 모두 `true`면 기동 확인이 끝난다. 실패하면 `docker compose -p edr-ai-triage-lab1-team logs --tail 100 <서비스명>`과 `Get-NetTCPConnection -LocalPort 9200,5601,5432,8000 -State Listen`으로 확인한다.

새 OpenSearch 프로젝트의 데이터 볼륨은 처음에는 비어 있다. PDF 적재는 `kb-playbooks` 인덱스를 **삭제하고 다시 만든다**. 기존 인덱스 데이터를 보존해야 하면 적재 전 백업 여부를 결정한다.

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m soc.kb.ingest
.\.venv\Scripts\python.exe -m soc.eval.rag_eval --mode all
```

실제 Recall@3에는 `.env`의 임베딩 API 키와 `FAKE_LLM=false`가 필요하다. 중지할 때는 `docker compose -p edr-ai-triage-lab1-team --profile app down`을 쓴다. `down -v`는 **팀 프로젝트의 OpenSearch·Postgres 볼륨 데이터를 삭제**하므로 재적재를 의도할 때만 쓴다.

**실행 기록 (2026-11-17):** 앞선 3.9.0 단일 노드 Compose로 120개 청크를 적재하고 하이브리드 Recall@3 **18/21**을 측정했다. 팀 파일로 교체한 뒤에는 이전 컨테이너를 `down`으로 내렸지만 볼륨은 삭제하지 않았다. 새 프로젝트에서 OpenSearch 2.19.0·Postgres 16·Dashboards 2.19.0을 기동하고 API 이미지를 빌드했다. 당시 이 PC에서만 5601 포트 충돌을 피하려고 Dashboards 호스트 포트를 **5602**로 바꿔 테스트했으며, 공유 Compose 설정은 **5601**로 되돌렸다. `docker compose ps`의 OpenSearch·Postgres는 `healthy`, OpenSearch 클러스터는 `green`/노드 1개, 당시 Dashboards `http://localhost:5602/`는 HTTP 200, SQL `select 1`은 `1`, API `/healthz`는 `ok`, `/readyz`는 `ready=true`, `opensearch=true`, `postgres=true`였다. 새 인덱스에 120개 청크를 적재한 후 21문항 재측정은 **키워드 17/21, 벡터 13/21, 하이브리드 18/21**이었다. 이전 3.9.0 결과(벡터 17/21, 하이브리드 18/21)와 벡터 수치가 다르지만, 버전 변경과 재적재가 함께 일어나 원인을 분리하지 않았다. 이 실습에서 별도의 깨 보기·진단 후 나눔은 수행하지 않았다.

## 공통 1차 확인
```bash
kubectl -n soc get pods,svc,ingress,pvc,jobs
kubectl -n soc get events --sort-by=.lastTimestamp | tail -20
```

## 장애 기록

### [단계-번호] 제목  (출제: 🔍/📘 · 진단: 🔍/📘 · 복구까지 걸린 시간: ____)
- **증상:**
- **확인 명령과 출력:**
- **원인:**
- **조치:**
- **진단 후 나눔** (깨 보기 규칙 5~6번)
  - 진단자: 가장 오래 걸린 지점과 이유
  - 출제자: 나라면 어디부터 봤을지
  - 다음에 같은 증상을 보면 처음 칠 명령:
- **재발 방지:**
- **고장 예상표와 비교:** 02 문서 9-2에서 예상했던 고장인가? 증상과 '처음 확인할 곳'은 맞았나?
