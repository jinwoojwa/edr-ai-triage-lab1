# 도구 입출력 계약

기준 코드: `src/soc/mocks.py`, `src/soc/telemetry/tools.py`, `src/soc/kb/search.py`.
이 문서는 기존 협의서를 현재 코드 골격의 반환 구조에 맞춰 다시 쓴 구현 목표다. 실제 조사 도구와 RRF 결합에는 아직 TODO가 있으므로, 아래 내용이 모두 구현됐다는 뜻은 아니다.

- 🔍 기록 담당: 좌진우 — 조사 도구 3개
- 📘 문서 담당: 이동원 — 플레이북 검색 도구 1개
- 계약을 바꿀 때는 두 사람이 합의하고 가짜 도구, 실제 도구, 호출부, 테스트를 함께 갱신한다.

## 공통 규칙

- 모든 조사 기록에는 **실제 조회한 `event_id`**가 있어야 한다. 기록이 없으면 ID를 만들어 넣지 않는다.
- 조사 기록 한 건의 기본 모양은 `summarize()`를 따른다: `event_id`, `ts`, `type`, `pid`, `ppid`, `name`, `cmdline`, `user`, `signed`. `detail`은 파일·네트워크 등 부가 정보가 있을 때만 붙는다. `cmdline`은 현재 코드 기준 앞 120자까지만 보낸다.
- 기록 한 건에는 `host`를 반복하지 않는다. 조사 도구의 최상위 `host`로 대상 PC를 표시한다. 검색에는 항상 `host`와 `pid`를 함께 사용해 다른 PC의 동일 PID가 섞이지 않게 한다.
- 플레이북 검색 결과에는 권고 출처를 나타내는 `source`(PDF 파일명)와 1부터 시작하는 `page`가 있어야 한다.
- 네 도구 모두 성공 시 **`error` 필드가 없는 기존 코드 구조**를 사용한다. 결과가 없을 때는 도구별 빈 결과를 반환한다. 잘못된 입력은 `ValueError`, 검색·백엔드 장애는 예외로 전달한다. 에이전트의 도구 실행 노드는 예외를 잡아 도구 호출 메시지에 오류를 표시한다. 다른 직접 호출부도 예외 처리가 필요하다.
- 숫자 범위와 형식 검증은 실제 함수와 가짜 함수 양쪽에 적용할 목표다. 현재 가짜 함수와 일부 호출부에는 아직 구현되지 않았다.

## 도구별 계약

| 도구 | 입력 | 정상 출력 | 결과 없음 | 개수·순서 |
| --- | --- | --- | --- | --- |
| `get_process_tree(host, pid)` | 비어 있지 않은 `host` 문자열, 0 이상의 정수 `pid` | `{host, pid, process, ancestors, children, note?}`. `process`는 요약 기록 또는 `null`. `ancestors`는 가까운 부모부터, `children`은 자식 요약 목록. 배열 위치가 관계를 나타내므로 별도 `relationship` 필드는 두지 않는다. | `process: null`, `ancestors: []`, `children: []` | 부모 최대 5단계, 자식 최대 20건. 자식은 `ts` 오름차순 후 `event_id`로 순서를 고정한다. |
| `get_process_activity(host, pid)` | 위와 같은 `host`, `pid` | `{host, pid, events}`. `events`는 해당 프로세스의 `network`, `file`, `registry`, `script` 기록 요약. | `events: []` | 가장 최근 기록 최대 50건을 고른 뒤 `ts` 오름차순으로 반환한다. `process` 생성 기록은 이 목록에 포함하지 않는다. |
| `get_host_timeline(host, around_ts, minutes=10)` | 비어 있지 않은 `host`, 시간대가 있는 ISO 8601 문자열 `around_ts`, 0보다 큰 정수 `minutes` | `{host, from, to, events, truncated}`. `from`과 `to`는 조회 범위의 ISO 8601 시각. `events`는 해당 PC의 모든 이벤트 종류의 요약. | `events: []`, `truncated: false` | 기준 시각 앞뒤 `minutes`분, 양 끝 포함. `ts` 오름차순, 최대 100건. 잘렸으면 `truncated: true`. |
| `search_playbook(query, k=3)` | 공백만으로 이루어지지 않은 한국어·영어 질문 문자열 `query`, 1~10의 정수 `k` | **목록** `[{source, page, category, text, score}, ...]`. `category`는 파서의 요소 종류이며 없으면 `null`. | `[]` | 관련도 높은 순서로 최대 `k`건. |

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

### 4. 플레이북 검색

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
- 플레이북에 관련 문서가 없으면 `[]`.
- 예: `k=0`, 빈 `query`, 잘못된 `around_ts`에는 `ValueError`. OpenSearch·임베딩 장애에는 예외를 전달한다. 오류를 빈 결과로 가장하지 않는다.

## 호출부와 테스트 반영 항목

- `mocks.py`: 위 반환 구조를 유지하고 입력 검증과 개수 제한을 맞춘다. mock 점수는 가짜 값임을 표시한다.
- `telemetry/tools.py`: TODO[REC-2~4]를 구현하며 `summarize()`의 실제 `event_id`를 유지한다. `host`+`pid` 필터, 부모 5단계·자식 20건·활동 50건·타임라인 100건을 확인한다.
- `kb/search.py`: 내부 평가용 `search()`는 목록을 유지한다. 외부 도구 `search_playbook()`도 목록을 반환하며 `query`와 `k`를 검증한다.
- `agent/nodes.py`: 조사 도구의 예외를 도구 메시지로 전달한다. `playbook`은 목록으로 보관해 출처를 수집한다.
- `api/dify.py`: 검색 예외를 HTTP 오류로 매핑하고 RRF 점수를 Dify용 0~1 범위로 별도 변환한다.
- `tests/`: 출력 구조, 입력 오류, 빈 결과, 개수 제한, 호스트 혼합 방지, 실제 `event_id`와 `source` 보존을 확인한다.

## 변경 이력

| 변경 | 이유 | 합의 상태 |
| --- | --- | --- |
| 공통 `{items, error}`를 도구별 코드 골격의 반환 구조로 변경 | 가짜 도구·에이전트·기존 테스트와 일치시키기 위해 | 상대 검토 필요 |
| `relationship`, `summary` 대신 배열 위치와 `summarize()` 필드를 사용 | 현재 조사 도구의 데이터 모양과 일치시키기 위해 | 상대 검토 필요 |
| `search_playbook`을 목록 반환으로 명시하고 점수를 RRF 원점수로 설명 | 현재 검색·Dify 호출 방식과 점수 계산에 맞추기 위해 | 상대 검토 필요 |
| 결과 없음은 빈 결과, 입력·검색 장애는 예외로 구분 | 공통 `error` 필드 제거에 따른 실패 의미를 명확히 하기 위해 | 상대 검토 필요 |

