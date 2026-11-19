# 도구 입출력 계약

기준 코드: `src/soc/mocks.py`, `src/soc/telemetry/tools.py`, `src/soc/kb/search.py`.
이 문서는 기존 협의서를 현재 코드 골격의 반환 구조에 맞춰 다시 쓴 구현 목표다. 실제 조사 도구와 RRF 결합에는 아직 TODO가 있으므로, 아래 내용이 모두 구현됐다는 뜻은 아니다.

- 🔍 기록 담당: 좌진우 — 기존 조사 도구 3개. D2-7의 네 번째 조사 도구는 📘 문서 담당자가 교차 구현하고 🔍 기록 담당자가 리뷰해 승인했다. 리뷰에서 낸 개선 2건(간격 통계, `until_ts`)은 🔍가 반영했고 📘 확인을 기다린다.
- 📘 문서 담당: 이동원 — 플레이북 검색 도구 1개
- 계약을 바꿀 때는 두 사람이 합의하고 가짜 도구, 실제 도구, 호출부, 테스트를 함께 갱신한다.

## 공통 규칙

- 모든 조사 기록에는 **실제 조회한 `event_id`**가 있어야 한다. 기록이 없으면 ID를 만들어 넣지 않는다.
- 조사 기록 한 건의 기본 모양은 `summarize()`를 따른다: `event_id`, `ts`, `type`, `pid`, `ppid`, `name`, `cmdline`, `user`, `signed`. `detail`은 파일·네트워크 등 부가 정보가 있을 때만 붙는다. `cmdline`은 현재 코드 기준 앞 120자까지만 보낸다.
- 기록 한 건에는 `host`를 반복하지 않는다. 조사 도구의 최상위 `host`로 대상 PC를 표시한다. 프로세스 단위 검색에는 `host`와 `pid`를 함께 사용해 다른 PC의 동일 PID가 섞이지 않게 하고, 호스트 단위 검색에는 `host`를 필터로 사용한다.
- 플레이북 검색 결과에는 권고 출처를 나타내는 `source`(PDF 파일명)와 1부터 시작하는 `page`가 있어야 한다.
- 다섯 도구 모두 성공 시 **`error` 필드가 없는 기존 코드 구조**를 사용한다. 결과가 없을 때는 도구별 빈 결과를 반환한다. 잘못된 입력은 `ValueError`, 검색·백엔드 장애는 예외로 전달한다. 에이전트의 도구 실행 노드는 예외를 잡아 도구 호출 메시지에 오류를 표시한다. 다른 직접 호출부도 예외 처리가 필요하다.
- 숫자 범위와 형식 검증은 실제 함수와 가짜 함수 양쪽에 적용할 목표다. 현재 가짜 함수와 일부 호출부에는 아직 구현되지 않았다.

## 도구별 계약

| 도구 | 입력 | 정상 출력 | 결과 없음 | 개수·순서 |
| --- | --- | --- | --- | --- |
| `get_process_tree(host, pid)` | 비어 있지 않은 `host` 문자열, 0 이상의 정수 `pid` | `{host, pid, process, ancestors, children, note?}`. `process`는 요약 기록 또는 `null`. `ancestors`는 가까운 부모부터, `children`은 자식 요약 목록. 배열 위치가 관계를 나타내므로 별도 `relationship` 필드는 두지 않는다. | `process: null`, `ancestors: []`, `children: []` | 부모 최대 5단계, 자식 최대 20건. 자식은 `ts` 오름차순 후 `event_id`로 순서를 고정한다. |
| `get_process_activity(host, pid)` | 위와 같은 `host`, `pid` | `{host, pid, events}`. `events`는 해당 프로세스의 `network`, `file`, `registry`, `script` 기록 요약. | `events: []` | 가장 최근 기록 최대 50건을 고른 뒤 `ts` 오름차순으로 반환한다. `process` 생성 기록은 이 목록에 포함하지 않는다. |
| `get_host_timeline(host, around_ts, minutes=10)` | 비어 있지 않은 `host`, 시간대가 있는 ISO 8601 문자열 `around_ts`, 0보다 큰 정수 `minutes` | `{host, from, to, events, truncated}`. `from`과 `to`는 조회 범위의 ISO 8601 시각. `events`는 해당 PC의 모든 이벤트 종류의 요약. | `events: []`, `truncated: false` | 기준 시각 앞뒤 `minutes`분, 양 끝 포함. `ts` 오름차순, 최대 100건. 잘렸으면 `truncated: true`. |
| `get_network_connections(host, minutes, until_ts=None)` | 비어 있지 않은 `host`, 0보다 큰 정수 `minutes`, 선택 `until_ts`(시간대가 있는 ISO 8601 문자열, 생략하면 현재 시각) | `{host, from, to, connections, truncated}`. `connections`의 항목은 `{dst_ip, count, first_ts, last_ts, avg_interval_seconds, min_interval_seconds, max_interval_seconds, interval_stddev_seconds, events, events_truncated}`. `events`는 실제 `event_id`를 가진 네트워크 기록 요약. | `connections: []`, `truncated: false` | `until_ts`(없으면 호출 시 UTC 현재 시각)부터 직전 `minutes`분(양 끝 포함). 최근 네트워크 기록 최대 1,000건을 IP별로 집계하고 `count` 내림차순·IP 오름차순으로 최대 20개 IP를 반환. IP별 근거는 최근 5건을 시간순으로 반환. |
| `search_playbook(query, k=3)` | 공백만으로 이루어지지 않은 한국어·영어 질문 문자열 `query`, 1~10의 정수 `k` | **목록** `[{source, page, category, text, score}, ...]`. `category`는 파서의 요소 종류이며 없으면 `null`. | `[]` | 관련도 높은 순서로 최대 `k`건. |

`get_network_connections`는 IPv4 사설망(`10/8`, `172.16/12`, `192.168/16`)과 IPv6 고유 로컬(`fc00::/7`), 루프백·링크 로컬·멀티캐스트·미지정 주소를 제외한다. 실습용 문서 IP `198.51.100.0/24`, `203.0.113.0/24`는 외부 목적지로 취급한다. 같은 IP의 연속 연결 간격을 시간순으로 구해 평균·최소·최대와 표준편차(모집단)를 초 단위로 소수 둘째 자리까지 반환하며, 한 건뿐이어서 간격이 없으면 네 값이 모두 `null`이다(두 건이면 간격이 하나라 표준편차는 `0.0`). **평균만으로는 규칙적인 비컨과 불규칙한 정상 통신을 구분할 수 없으므로** 규칙성은 표준편차와 최소·최대로 판단한다. 표준편차가 작고 최소·최대가 평균에 가까우면 규칙적이고, 표준편차가 평균만큼 크면 불규칙하다. `events_truncated`는 해당 IP의 근거가 5건을 초과할 때 참이다. `truncated`는 전체 조회가 1,000건 또는 IP 20개 제한에 걸렸다는 뜻이며, 이때 `count`와 간격은 조회된 범위에 한정된다.

`until_ts`를 생략하면 현재 시각 기준이라 오래된 알림이나 고정 시각의 시뮬레이터 기록은 빈 결과가 나온다. 이 빈 결과는 "통신 없음"이 아니라 조회 구간에 기록이 없다는 뜻일 수 있으므로, 오래된 알림은 `until_ts`에 알림 시각(또는 그보다 조금 뒤)을 넘겨 조사하고 응답의 `from`·`to`가 알림 시각을 포함하는지 확인한다. 조회 구간은 `[until_ts - minutes, until_ts]`로 한쪽만 거슬러 올라가며, 앞뒤를 모두 보는 `get_host_timeline`과 다르다. `until_ts`는 UTC로 바꿔 `from`·`to`에 반영한다.

### 검색 점수의 의미

`search_playbook`의 실제 하이브리드 검색은 키워드와 벡터 검색 결과의 **순위**를 RRF로 합친다. 각 목록에서 순위가 `r`인 청크에 `1 / (60 + r)`을 더한 원점수이며, 공격 확률이나 판정 신뢰도가 아니다. 두 목록만 결합하므로 이론상 최대값은 `2 / 61 ≈ 0.03279`다. 아래 수치는 설명용이다. 현재 `mocks.py`의 `0.91` 같은 값은 가짜 견본 점수이며 RRF 점수로 해석하지 않는다. Dify의 0~1 점수는 별도 변환이 필요하다.

## 출력값 예시

### 1. 프로세스 트리

```json
{
  "host": "WS-007",
  "pid": 40702,
  "process": {
    "event_id": "evt-00000023",
    "ts": "2026-11-16T09:12:02Z",
    "type": "process",
    "pid": 40702,
    "ppid": 19329,
    "name": "rundll32.exe",
    "cmdline": "rundll32.exe ... comsvcs.dll ... MiniDump ...",
    "user": "kim",
    "signed": true
  },
  "ancestors": [
    {
      "event_id": "evt-00000022",
      "ts": "2026-11-16T09:12:01Z",
      "type": "process",
      "pid": 19329,
      "ppid": 8015,
      "name": "cmd.exe",
      "cmdline": "cmd.exe",
      "user": "kim",
      "signed": true
    }
  ],
  "children": [],
  "note": "그 위 부모의 생성 기록은 확인되지 않았습니다."
}
```

### 2. 프로세스 활동

```json
{
  "host": "WS-007",
  "pid": 40702,
  "events": [
    {
      "event_id": "evt-00000024",
      "ts": "2026-11-16T09:12:03Z",
      "type": "file",
      "pid": 40702,
      "ppid": 19329,
      "name": "rundll32.exe",
      "cmdline": "rundll32.exe ... comsvcs.dll ... MiniDump ...",
      "user": "kim",
      "signed": true,
      "detail": "create C:\\Windows\\Temp\\d.dmp"
    }
  ]
}
```

### 3. 호스트 타임라인

```json
{
  "host": "WS-007",
  "from": "2026-11-16T09:11:02Z",
  "to": "2026-11-16T09:13:02Z",
  "events": [
    {
      "event_id": "evt-00000023",
      "ts": "2026-11-16T09:12:02Z",
      "type": "process",
      "pid": 40702,
      "ppid": 19329,
      "name": "rundll32.exe",
      "cmdline": "rundll32.exe ... comsvcs.dll ... MiniDump ...",
      "user": "kim",
      "signed": true
    },
    {
      "event_id": "evt-00000024",
      "ts": "2026-11-16T09:12:03Z",
      "type": "file",
      "pid": 40702,
      "ppid": 19329,
      "name": "rundll32.exe",
      "cmdline": "rundll32.exe ... comsvcs.dll ... MiniDump ...",
      "user": "kim",
      "signed": true,
      "detail": "create C:\\Windows\\Temp\\d.dmp"
    }
  ],
  "truncated": false
}
```

### 4. 외부 네트워크 연결 요약

아래 시각과 ID는 반환 형식을 보여 주는 예시다.

```json
{
  "host": "WS-007",
  "from": "2026-11-16T09:00:00Z",
  "to": "2026-11-16T09:10:00Z",
  "connections": [{
    "dst_ip": "198.51.100.23",
    "count": 2,
    "first_ts": "2026-11-16T09:02:00Z",
    "last_ts": "2026-11-16T09:02:30Z",
    "avg_interval_seconds": 30.0,
    "min_interval_seconds": 30.0,
    "max_interval_seconds": 30.0,
    "interval_stddev_seconds": 0.0,
    "events": [
      {"event_id": "evt-00000025", "ts": "2026-11-16T09:02:00Z", "type": "network", "pid": 40702, "ppid": 19329, "name": "powershell.exe", "cmdline": "powershell.exe ...", "user": "kim", "signed": true, "detail": "198.51.100.23:443 (300 bytes)"},
      {"event_id": "evt-00000026", "ts": "2026-11-16T09:02:30Z", "type": "network", "pid": 40702, "ppid": 19329, "name": "powershell.exe", "cmdline": "powershell.exe ...", "user": "kim", "signed": true, "detail": "198.51.100.23:443 (300 bytes)"}
    ],
    "events_truncated": false
  }],
  "truncated": false
}
```

### 5. 플레이북 검색

```json
[
  {
    "source": "01_response_policy_tables.pdf",
    "page": 1,
    "category": "Table",
    "text": "호스트 네트워크 격리 | 승인권자: SOC 팀장",
    "score": 0.03278
  },
  {
    "source": "02_playbook_credential_dump.pdf",
    "page": 1,
    "category": "NarrativeText",
    "text": "자격증명 덤프가 의심되면 추가 조사와 격리를 검토한다.",
    "score": 0.0161
  }
]
```

검색 결과의 문구·순위·페이지·점수는 실제 검색을 실행해 확인한 값이 아닌 **형식 예시**다.

## 결과 없음과 오류 예시

- 트리 대상이 없으면 `{ "host": "WS-007", "pid": 99999, "process": null, "ancestors": [], "children": [] }`.
- 프로세스 활동이 없으면 `{ "host": "WS-007", "pid": 99999, "events": [] }`.
- 타임라인에 기록이 없으면 `{ "host": "WS-007", "from": "2026-11-16T09:00:00Z", "to": "2026-11-16T09:02:00Z", "events": [], "truncated": false }`.
- 조회 구간에 외부 네트워크 기록이 없으면 `{ "host": "WS-007", "from": "...", "to": "...", "connections": [], "truncated": false }`.
- 플레이북에 관련 문서가 없으면 `[]`.
- 예: `k=0`, 빈 `query`, 잘못된 `around_ts`, 네트워크 도구의 빈 `host`·0 이하 또는 정수가 아닌 `minutes`·시간대 없는 `until_ts`에는 `ValueError`. OpenSearch·임베딩 장애에는 예외를 전달한다. 오류를 빈 결과로 가장하지 않는다.

## 호출부와 테스트 반영 항목

- `mocks.py`: 기존 네 도구의 반환 구조를 유지하고 입력 검증과 개수 제한을 맞춘다. mock 점수는 가짜 값임을 표시한다. D2-7 네트워크 도구는 실제 도구 목록에만 등록하고 mock에는 넣지 않는 것이 🔍 기록 담당자의 리뷰 의견이다(가짜 LLM이 처음 두 도구만 쓰고 기존 세 도구가 견본으로 충분하다). 📘 확인 대기.
- `telemetry/tools.py`: TODO[REC-2~4]를 구현하며 `summarize()`의 실제 `event_id`를 유지한다. `host`+`pid` 필터, 부모 5단계·자식 20건·활동 50건·타임라인 100건을 확인한다.
- `telemetry/tools.py`: D2-7 네트워크 도구는 `host`·시간 구간 필터, 외부 IP 분류, 횟수·간격 집계(평균·최소·최대·표준편차), `until_ts` 구간 이동과 시간대 변환, 실제 `event_id` 보존을 확인한다. 실제 도구 목록 등록 후 에이전트의 도구 선택·근거 ID 수집 경로도 확인한다.
- `kb/search.py`: 내부 평가용 `search()`는 목록을 유지한다. 외부 도구 `search_playbook()`도 목록을 반환하며 `query`와 `k`를 검증한다.
- `agent/nodes.py`: 조사 도구의 예외를 도구 메시지로 전달한다. `playbook`은 목록으로 보관해 출처를 수집한다.
- `api/dify.py`: 검색 예외를 HTTP 오류로 매핑하고 RRF 점수를 Dify용 0~1 범위로 별도 변환한다.
- `tests/`: 출력 구조, 입력 오류, 빈 결과, 개수 제한, 호스트 혼합 방지, 실제 `event_id`와 `source` 보존을 확인한다.

## 외부 API 공개와 유료 호출 인증 (2026-11-19)

실습 합성 데이터는 공개한다는 사용자 결정에 따라 무료 API에는 인증을 요구하지 않는다. 외부 호스트는 `https://soc.1.201.110.16.nip.io`이며 실제 적용·검증 상태는 RUNBOOK을 따른다.

| 경로 / 메서드 | 인증 | 동작·오류 계약 |
| --- | --- | --- |
| GET /docs, /openapi.json | 없음 | Swagger와 schema 공개, Dify operation은 schema에서 제외 |
| GET /alerts, /alerts/{id}, /reports/{id}, /approvals, /stats | 없음 | 합성 경보·근거·리포트·승인 대기 조회; 없는 ID는 기존 404 |
| POST /alerts/{id}/triage | Authorization: Bearer 전용 키 | TRIAGE_API_KEY와 상수 시간 비교. 누락/잘못된 키·scheme 401, WWW-Authenticate: Bearer. 서버 키 미설정은 503. 거절 시 조회·상태 변경·그래프/모델 실행 없음 |
| POST /approvals/{id} | 없음 | pending_approval이며 checkpoint.next=(approval,)·interrupt 존재일 때만 재개. 다른 경보 상태·노드이면 409, 저장된 다음 단계 없음은 410. 정상 승인→report는 추가 chat/embedding 호출 없음 |
| GET /healthz | 없음 | HTTP 기존 200 및 HTTPS 지원. CI 관측 경로 유지 |
| /readyz | 내부 probe용 | 외부 Ingress에는 공개하지 않음 |
| /dify/retrieval, 기타 경로 | 외부 공개 제외 | Dify 구현·연동은 이번 범위 아님 |

TRIAGE_API_KEY는 OpenAI 제공자 키와 다른 전용 Secret이다. Swagger Authorize에 키 값만 입력하면 Bearer 헤더가 붙는다. 무료 operation에는 OpenAPI security를 설정하지 않는다. 키 값은 schema·응답·URL에 포함하지 않는다. 실제 유료 호출은 HTTPS로만 요청한다. HTTP의 docs·업무 경로는 HTTPS로 이동하며 HTTP에 키를 먼저 보내지 않는다.

무인증 승인의 approver는 실습용 입력 이름이며 신원을 보증하지 않는다. 공유 키는 사용자별 권한·비용 상한·동시 재처리 방지를 제공하지 않는다. 향후 유료 임베딩 검색을 공개하면 그 route도 비용 기준으로 보호한다.

## 변경 이력

| 변경 | 이유 | 합의 상태 |
| --- | --- | --- |
| 공통 `{items, error}`를 도구별 코드 골격의 반환 구조로 변경 | 가짜 도구·에이전트·기존 테스트와 일치시키기 위해 | 상대 검토 필요 |
| `relationship`, `summary` 대신 배열 위치와 `summarize()` 필드를 사용 | 현재 조사 도구의 데이터 모양과 일치시키기 위해 | 상대 검토 필요 |
| `search_playbook`을 목록 반환으로 명시하고 점수를 RRF 원점수로 설명 | 현재 검색·Dify 호출 방식과 점수 계산에 맞추기 위해 | 상대 검토 필요 |
| 결과 없음은 빈 결과, 입력·검색 장애는 예외로 구분 | 공통 `error` 필드 제거에 따른 실패 의미를 명확히 하기 위해 | 상대 검토 필요 |
| D2-7 `get_network_connections(host, minutes)` 추가: 외부 IP별 횟수·간격·실제 `event_id` 근거와 조회 제한을 명시 | 주기적인 외부 통신을 조사하는 도구를 문서 담당자가 기록 담당자 영역에 교차 구현 | 🔍 기록 담당자 리뷰 완료·승인 (개선 2건은 아래 행) |
| `get_network_connections`에 `min_interval_seconds`, `max_interval_seconds`, `interval_stddev_seconds`와 선택 인자 `until_ts` 추가. mock에는 넣지 않음 | 평균 간격만으로는 비컨과 정상 통신을 구분할 수 없다(시뮬레이터 WS-010 10분 창에서 비컨 30.0초, 정상 SaaS 26.72초). 현재 시각 기준 조회는 오래된 알림에서 "통신 없음"과 구분되지 않는 빈 결과를 낸다 | 🔍 제안·반영 완료(코드·테스트·문서). **📘 이동원 확인 대기, 둘 다 동의한 것은 아님** |
| 2026-11-19: 공개 API의 비용 기준 인증. triage만 Bearer 전용 키·401/503, 무료 조회·승인 무인증. 승인 체크포인트를 approval interrupt로 제한 | 외부 docs/API 이용과 유료 모델 호출 차단을 함께 제공. 무인증 승인으로 유료 단계를 재개하지 못하게 함 | 사용자 정책에 따라 구현, 담당자 교차 리뷰는 별도 |

