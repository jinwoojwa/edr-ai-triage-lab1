# 도구 계약

> 1일차에 함께 정합니다. **혼자 바꾸지 않습니다.** 바꾸려면 상대에게 먼저 말하고, 이 표와 `src/soc/mocks.py`를 같이 고친 뒤 변경 이력에 적습니다.

🔍 기록 담당: 좌진우 📘 문서 담당: 이동원 (둘 다 이름을 적으면 계약 성립)

## 도구 목록

| 도구                                          | 만드는 사람 | 입력 | 출력 (꼭 있어야 하는 칸)               | 결과 개수 상한 | 실패하면 |
| --------------------------------------------- | ----------- | ---- | -------------------------------------- | -------------- | -------- |
| `get_process_tree(host, pid)`                 | 🔍 좌진우 | host, pid | event_id, host, pid, ppid, name, relationship(target·`parent`·`child`) | 부모 최대 5단계, 자식 최대 20건 | 대상 기록 없음: items=[], error=null. 부모 기록이 없으면 확인된 항목만 반환. 입력 오류·검색 장애: items=[], error에 오류 코드와 설명 |
| `get_process_activity(host, pid)`             | 🔍 좌진우 | host, pid | event_id, ts, host, pid, type, summary | 최신 50건 | 활동 기록 없음: items=[], error=null. 입력 오류·검색 장애: items=[], error에 오류 코드와 설명 |
| `get_host_timeline(host, around_ts, minutes)` | 🔍 좌진우 | host, around_ts, minutes | event_id, ts, host, type, summary | 시간순 100건 | 해당 시간대 기록 없음: items=[], error=null. 시간 형식·`minutes` 오류 또는 검색 장애: items=[], error에 오류 코드와 설명 |
| `search_playbook(query, k)`                   | 📘 이동원 | `query`: 한국어 또는 영어 질문 문자열, `k`: 원하는 결과 개수(1~10) | `text`, `source`(PDF 파일명), `page`(1부터 시작), `score` | `k`건 | 관련 문서 없음: items=[], error=null. query·`k` 오류 또는 검색 장애: items=[], error에 오류 코드와 설명 |

### 출력값 예시:
- get_process_tree
{
  "items": [
    {
      "event_id": "evt-00000022",
      "host": "WS-007",
      "pid": 19329,
      "ppid": 8015,
      "name": "cmd.exe",
      "relationship": "parent"
    },
    {
      "event_id": "evt-00000023",
      "host": "WS-007",
      "pid": 40702,
      "ppid": 19329,
      "name": "rundll32.exe",
      "relationship": "target"
    }
  ],
  "error": null
}
- get_process_activity
{
  "items": [
    {
      "event_id": "evt-00000023",
      "ts": "2026-11-16T09:12:02Z",
      "host": "WS-007",
      "pid": 40702,
      "type": "process",
      "summary": "rundll32.exe가 comsvcs.dll의 MiniDump 기능을 실행"
    },
    {
      "event_id": "evt-00000024",
      "ts": "2026-11-16T09:12:03Z",
      "host": "WS-007",
      "pid": 40702,
      "type": "file",
      "summary": "C:\\Windows\\Temp\\d.dmp 파일 생성"
    }
  ],
  "error": null
}
- get_host_timeline
{
  "items": [
    {
      "event_id": "evt-00000022",
      "ts": "2026-11-16T09:12:01Z",
      "host": "WS-007",
      "type": "process",
      "summary": "cmd.exe 실행"
    },
    {
      "event_id": "evt-00000023",
      "ts": "2026-11-16T09:12:02Z",
      "host": "WS-007",
      "type": "process",
      "summary": "cmd.exe가 rundll32.exe를 실행해 MiniDump 기능 호출"
    },
    {
      "event_id": "evt-00000024",
      "ts": "2026-11-16T09:12:03Z",
      "host": "WS-007",
      "type": "file",
      "summary": "C:\\Windows\\Temp\\d.dmp 파일 생성"
    }
  ],
  "error": null
}
- search_playbook
{
  "items": [
    {
      "text": "호스트 격리 조치는 SOC 팀장 승인 후 진행한다.",
      "source": "01_response_policy_tables.pdf",
      "page": 2,
      "score": 0.82
    },
    {
      "text": "자격증명 덤프가 의심되면 호스트 격리와 추가 조사를 검토한다.",
      "source": "02_playbook_credential_dump.pdf",
      "page": 1,
      "score": 0.71
    }
  ],
  "error": null
}


## 꼭 합의할 것

- 🔍 텔레메트리 도구의 모든 결과에는 **`event_id`**가 있다. → 가드레일이 판정 근거를 추적하는 데 씁니다 (2일차 `G-1`).
- 📘 플레이북 검색 결과에는 **`source`(파일 이름)**가 있다. → 권고에 출처를 붙이는 데 씁니다.

## 변경 이력

| 바꾼 것 | 이유 | 둘 다 동의 |
| ------- | ---- | ---------- |
