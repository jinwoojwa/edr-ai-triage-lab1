# 사전 자료 2. 트러블슈팅: 왜 하고, 어떻게 하는가

> 읽는 시간 30분 + 혼자 정리 25분. **1~4장은 개념**, **5~8장은 실습 중에 다시 펴 볼 참고**입니다. **9장만 지금 직접** 합니다.

## 1. 왜 트러블슈팅을 배우는가

- **시스템은 반드시 고장 납니다.** 설정 오타, 메모리 부족, 네트워크 차단, 외부 API 장애. 문제는 "고장이 나느냐"가 아니라 **"얼마나 빨리 찾고 고치느냐"**입니다.
- **소프트웨어는 만드는 시간보다 운영하는 시간이 훨씬 깁니다.** 실무에서 인프라·플랫폼 엔지니어의 하루는 대부분 "왜 안 되지?"를 푸는 일입니다.
- **전문성은 '왜 안 되는지'를 파고들 때 쌓입니다.** 정상 동작만 본 사람은 시스템을 반만 압니다. Google SRE 책은 트러블슈팅이 타고나는 감이 아니라 **배우고 가르칠 수 있는 기술**이라고 말합니다.
- **AI 서비스는 고장 지점이 더 많습니다.** 인프라뿐 아니라 "검색이 엉뚱한 문서를 가져옴", "LLM이 근거를 지어냄", "API가 느려 시간 초과"도 장애입니다.
- **면접에서 가장 많이 받는 질문**이기도 합니다. "장애를 겪고 해결한 경험을 설명해 보세요."

## 2. 기본 절차: 감이 아니라 순서로

Google SRE 책 12장(Effective Troubleshooting)의 흐름을 우리 실습에 맞게 줄였습니다.

```
① 문제 정의 ─► ② 분류(트리아지) ─► ③ 관찰 ─► ④ 가설 ─► ⑤ 검증 ─► ⑥ 조치 ─► ⑦ 기록
     ▲                                          │
     └──────────── 가설이 틀렸으면 다시 ◄──────────┘
```

| 단계 | 할 일 | 실습 예 |
|---|---|---|
| ① 문제 정의 | **기대 동작 / 실제 동작 / 재현 방법**을 한 줄씩 | "승인하면 리포트가 completed여야 하는데 502가 난다. 승인 API를 호출할 때마다 재현됨" |
| ② 분류 | 얼마나 급한가? 먼저 피해를 줄일 수 있나? | 롤백하면 일단 서비스가 되는가 → 되면 먼저 롤백하고 원인은 그다음 |
| ③ 관찰 | 추측 전에 **데이터**를 본다 | `kubectl get pods`, `describe`, `logs`, `events`, 메트릭 |
| ④ 가설 | 관찰과 맞는 원인 후보를 **여러 개** | "readiness 실패?", "Service selector 불일치?", "앱 예외?" |
| ⑤ 검증 | 가설을 **하나씩** 확인하는 명령 | `kubectl get endpointslices` → 비어 있으면 selector 쪽 |
| ⑥ 조치 | **한 번에 하나만** 바꾸고 다시 확인 | selector 수정 → apply → 재확인 |
| ⑦ 기록 | 런북에 증상·명령·출력·원인·조치 | `docs/RUNBOOK.md` |

## 3. 쿠버네티스에서 '어디를 볼지' 순서

위에서 아래로 좁혀 갑니다. **아래층이 깨지면 위층은 전부 깨진 것처럼 보입니다.**

| 층 | 질문 | 명령 |
|---|---|---|
| 노드 | 서버 자체는 괜찮은가? (메모리, 디스크) | `kubectl get nodes`, `kubectl describe node`, `df -h`, `free -h` |
| 파드 배치 | 파드가 노드에 올라갔나? | `kubectl get pods` → `Pending`이면 `describe pod`의 Events |
| 이미지 | 이미지를 받았나? | `ImagePullBackOff` → 이미지 이름·태그·인증 |
| 컨테이너 시작 | 시작은 했나? 왜 죽었나? | `CrashLoopBackOff` → `kubectl logs --previous` |
| 설정 | 환경변수·시크릿이 들어갔나? | `CreateContainerConfigError` → `kubectl get secret,configmap` |
| 헬스체크 | 프로브가 통과하나? | `Running`인데 `0/1` → `describe`의 `Readiness probe failed` |
| 서비스 연결 | Service가 파드를 찾았나? | `kubectl get endpointslices -l kubernetes.io/service-name=<이름>` |
| 외부 노출 | Ingress 규칙이 맞나? | 404(규칙 없음) vs 502(백엔드 없음) vs 504(시간 초과) |
| 앱 | 앱 로직은? | 앱 로그, `/readyz`, 트레이스 |

> **이벤트가 1순위 단서입니다.** `kubectl get events --sort-by=.lastTimestamp`를 습관처럼 치세요.

## 4. 파이프라인 시스템의 트러블슈팅: "어디서 멈췄나"

이번 시스템은 데이터가 여러 단계를 흐릅니다. **증상은 끝에서 보이지만 원인은 중간에 있습니다.**

```
시뮬레이터 → [edr-events] → 탐지 룰 → [edr-alerts status=new] → 워커(에이전트) → [리포트] → API
```
각 칸의 **개수**를 세면 어디서 멈췄는지 바로 보입니다. 예를 들어 이벤트는 쌓이는데 `status=new` 알림이 줄지 않으면 워커가 문제예요.

## 5. AI 에이전트의 트러블슈팅 (LLMOps)

> 📖 **지금은 읽기만 하세요.** 2일차 '평가 기준점'에서 에이전트가 틀린 답을 낸 사례를 골라 원인을 찾을 때, 이 표를 펴 놓고 씁니다.

"답이 틀렸다"도 장애입니다. 어느 단계에서 틀렸는지 나눠서 봅니다.

| 증상 | 의심 단계 | 확인 |
|---|---|---|
| 판정 근거에 없는 이벤트가 등장 | 판정(LLM 환각) | 가드레일 결과, 그래프 trace |
| 악성인데 '의심'으로 나옴 | 조사(도구) | 도구가 이벤트를 찾았나? 아직 색인 전이었나? |
| 권고가 정책과 다름 | RAG | 정답 문서가 상위 3개 안에 있었나? (Recall@3) |
| 너무 느림 / 비쌈 | 루프·예산 | 도구 호출 횟수, 토큰 수, 단계별 시간 |

## 6. 하지 말아야 할 것 (안티패턴)

> 📖 **지금은 읽기만 하세요.** 실습 내내 장애를 고칠 때마다 지키는 규칙입니다. 짝이 이 중 하나를 하면 서로 알려 주세요.

- **일단 재시작부터:** 증거(로그)가 사라집니다. 먼저 `logs --previous`와 `describe`부터 보세요.
- **여러 개를 동시에 바꾸기:** 고쳐져도 왜 고쳐졌는지 모릅니다.
- **추측으로 고치기:** "아마 메모리겠지"가 아니라 `OOMKilled`를 확인하고 고치세요.
- **고치고 기록 안 하기:** 다음 주에 같은 장애로 같은 시간을 씁니다.
- **누구 탓하기:** 회고는 사람이 아니라 시스템과 절차의 문제를 찾습니다(blameless).

## 7. 이번 실습에서의 방식: "깨 보기"

> 📖 **지금은 규칙만 알아 두세요.** 1일차 오후 인프라 0단계부터 단계마다 직접 합니다. 진행 방법은 `guide/INFRA_STAGES.md`에 다시 나옵니다.

인프라는 **단계마다 짝이 일부러 장애를 넣고, 내가 찾습니다.**
- **출제자:** 장애를 하나 넣고, 무엇을 넣었는지 종이에 적어 덮어 둡니다.
- **진단자:** 위 절차대로 찾습니다. 출제자는 힌트를 주지 않습니다.
- **시간을 잽니다.** 찾은 뒤 `RUNBOOK.md`에 기록하고 역할을 바꿉니다.

## 8. 좋은 런북 vs 나쁜 런북

> 📖 **지금은 형식만 봐 두세요.** 깨 보기로 장애를 찾을 때마다 `docs/RUNBOOK.md`에 오른쪽(좋은 예) 형식으로 기록합니다.

| 나쁜 예 | 좋은 예 |
|---|---|
| "OpenSearch가 죽으면 다시 띄운다." | **증상:** `opensearch-0`이 `CrashLoopBackOff` |
| | **확인:** `kubectl logs opensearch-0 --previous` → `max virtual memory areas vm.max_map_count [65530] is too low` |
| | **원인:** 서버의 커널 설정값이 OpenSearch 요구치보다 작음 |
| | **조치:** 서버에서 `sudo sysctl -w vm.max_map_count=262144`, 영구 설정은 `/etc/sysctl.d/` → 파드 재시작 |
| | **재발 방지:** 서버 초기 설정 스크립트에 포함 |

## 9. 혼자 정리하기 (25분)

> ✏️ **이 장은 지금 직접 합니다.** 짝과 나누지 말고 **각자** 하고, 결과는 개인 노트에 적어 둡니다. 2일차에 `docs/RUNBOOK.md`로 옮겨 씁니다.

### 9-1. 장애 신고 하나를 2장 순서대로 풀어 보기 (10분)

실제 서버 없이, **주어진 명령 결과만 보고** 2장의 순서(문제 정의 → 관찰 → 가설 → 검증)를 따라가 봅니다.

**장애 신고 (팀장이 보낸 메시지)**
> "아침부터 알림은 계속 들어오는데, 에이전트 리포트가 하나도 안 나와요. 어제 저녁까지는 됐어요."

**① 문제 정의:** 아래 빈칸을 채워 보세요.
```
기대 동작 : 
실제 동작 : 
언제부터  : 
```

**② 관찰:** 엔지니어가 3장 표의 순서대로 명령을 쳐서 아래 결과를 얻었습니다.

```
$ kubectl -n soc get pods
NAME                      READY   STATUS             RESTARTS   AGE
api-7c9d8f6b5-x2k4p       1/1     Running            0          2d
opensearch-0              1/1     Running            0          2d
postgres-0                1/1     Running            0          14h
worker-5f6c7d8e9-q8w2r    0/1     CrashLoopBackOff   37         14h
```

```
$ kubectl -n soc logs worker-5f6c7d8e9-q8w2r --previous
... connecting to postgres:5432 ...
psycopg.OperationalError: connection failed: FATAL:  password authentication failed for user "soc"
```

**③ 가설:** 위 결과에서 무엇이 이상한가요? 원인 후보를 **두 개** 적어 보세요.

**④ 검증:** 가설이 맞는지 확인하려면 무엇을 더 보면 될까요? (힌트: postgres-0의 AGE가 14h인 것과 연결해 보세요)

<details>
<summary>풀이 보기</summary>

**① 문제 정의**
- 기대 동작: 알림이 들어오면 에이전트가 처리해 리포트가 나온다.
- 실제 동작: 알림은 쌓이는데 리포트가 나오지 않는다.
- 언제부터: 어제 저녁 이후 (약 14시간 전)

**② 관찰에서 이상한 점**
- 다른 부품은 `Running`인데 **worker만 `CrashLoopBackOff`**이고, 37번이나 재시작했다. → "알림을 처리하는 부품(워커)이 멈췄다"는 01b의 표와 일치한다.
- 직전 로그(`--previous`)에 **Postgres 비밀번호 인증 실패**가 있다.
- `postgres-0`과 worker의 AGE가 둘 다 **14h**다. → 어제 저녁에 둘 다 새로 시작됐다.

**③ 가설**
- 가설 A: 워커가 가진 Postgres 비밀번호(시크릿)가 틀렸다.
- 가설 B: 어제 저녁 누군가 Postgres를 다시 만들면서 비밀번호가 바뀌었다.

**④ 검증**
- 어제 저녁에 시크릿이나 Postgres 설정을 바꾼 기록이 있는지 확인한다 (변경 기록, `kubectl get events`).
- 워커에 들어간 비밀번호와 Postgres가 실제로 쓰는 비밀번호를 비교한다.

**교훈:** 증상은 "리포트가 안 나온다"(맨 끝)였지만, 원인은 "워커 ↔ Postgres 사이의 비밀번호"(중간)에 있었습니다. 01b 4장에서 본 그대로입니다.
이런 장애는 2일차 인프라 3단계의 '깨 보기'에서 직접 만들어 보게 됩니다.

</details>

### 9-2. 내 역할의 '고장 예상표' 만들기 (15분)

실제로 고장 나기 전에 **어디가 어떻게 망가질지 미리 예상**해 봅니다. 실무에서는 이를 사전 부검(pre-mortem)이라고 부릅니다.
상상만 하지 말고, **실습에서 쓸 실제 자료를 열어 보면서** 합니다.

#### 🔍 기록 담당: 샘플 기록을 열어 보기

`data/telemetry/sample_events.jsonl`을 텍스트 편집기로 엽니다. 한 줄이 기록 하나입니다. (총 24줄)

1. WS-007의 `rundll32.exe` 줄을 찾고, 그 기록의 `ppid`(부모 번호)를 따라 부모 프로세스 줄을 찾아보세요. 01의 예시 알림이 실제 기록에서는 이렇게 생겼습니다.
2. WS-002의 `powershell.exe` 줄도 찾아보세요. 이것도 수상해 보이나요? (01 3장의 '오탐' 예시)
3. 이 기록을 보면서 **조사 도구가 틀린 결과를 낼 수 있는 경우**를 두 가지 예상해 보세요.
   - 예: 부모 프로세스의 기록이 아직 저장되지 않았다면? / 다른 PC에 같은 pid가 있다면?

#### 📘 문서 담당: PDF를 열어 보기

`data/kb/pdf/`의 PDF 중 아래 세 개를 열어 봅니다.

| 파일 | 열어서 볼 것 |
|---|---|
| `03_playbook_ransomware_header_footer.pdf` | 페이지마다 반복되는 위·아래 문구 ("대외비" 등) |
| `06_false_positive_guide_scanned.pdf` | 글자를 마우스로 선택(드래그)할 수 있나요? |
| `09_response_matrix_complex_tables.pdf` | 표의 합쳐진 칸, `〃` 표시, 다음 쪽으로 넘어가는 표 |

그리고 스스로 물어봅니다. **"컴퓨터가 이 문서를 글자로 읽으면 무엇이 망가질까?"**
문서 담당의 '고장'은 서버가 꺼지는 것만이 아닙니다. **문서가 망가진 채로 검색 창고에 들어가는 것**도 고장입니다. 그러면 에이전트는 엉뚱한 매뉴얼을 근거로 권고하게 됩니다.

#### 고장 예상표 (둘 다 같은 양식, 2줄 이상)

### D3-10 고장 예상표 마무리 — 2026-11-19

현재 세션의 **1~6단계 원본 명령 출력·복구 보고**와 [RUNBOOK](../RUNBOOK.md), [인프라 실습 안내](../guide/INFRA_STAGES.md), [DECISIONS](../DECISIONS.md)를 대조했다. 이어 사용자 요청으로 **7단계의 세 가지 고장을 직접 추가 주입·원복**하고 아래 결과를 반영했다. 1~6단계는 과거 기록이며, 최종 성능 평가는 이번 범위에 포함하지 않는다.

**기록의 범위:** 기존 개인 예상표는 예시와 빈칸만 있었으므로 아래 ‘예상’은 실습 안내의 기대 증상이다. 실제 결과를 사전 예측으로 소급하지 않는다. 최초 작성 때 RUNBOOK에 없어서 근거 미확인으로 둔 1~6단계 항목은 **세션 원본을 재열람해 실제 재현·복구 결과로 정정**했다. 요청·승인만으로 완료를 판단하지 않았으며, 과거 관측을 현재 서버의 재점검 결과로 표현하지 않는다.

- **일치:** 예상한 증상과 복구를 실제 출력으로 확인했다.
- **조건 명시:** 실제 재현·복구했지만 추가 조건이나 검증 범위를 함께 밝혀야 한다.
- **예상과 다름:** 고장은 재현됐으나 실제 HTTP 코드 등이 안내와 달랐다.
- **대체 검증:** 안내와 다른 고장을 주입해 같은 복구 목적을 검증했다.
- **별도 미검증:** 유사 기록은 있으나 해당 조건의 직접 주입 결과는 확인되지 않는다.

#### 세션 원본 근거

같은 세션 `01a1eceb-5ab8-7670-ac5d-062aa4a94b53`의 아래 턴에서 명령 출력과 최종 보고를 확인했다. 시간은 2026-11-19 KST의 요청 시작 시각이며 복구 소요 시간이 아니다. S1~S6는 아래 표의 출처 표기다. 비밀번호·키·Secret 원문은 옮기지 않았다.

| 출처 | 시각 / 원본 턴 ID | 확인한 정리·원복 근거 |
| --- | --- | --- |
| S1 | 11:29 / `01a1f1a3-7409-7ba0-b22d-f40c72159971` | 테스트 Pod 0·Deployment/Service 제거·임시 kubeconfig 0·운영 설정 동일 |
| S2 | 11:33 / `01a1f1a7-3a36-7942-a422-154c4f3d9967` | sysctl 262144·영구 파일 해시 동일·테스트 namespace/PV 제거·복구 타이머 0 |
| S3 | 11:42 / `01a1f1af-5ed4-79a2-9f83-7b40995bab5b` | 테스트 Secret 제거·테스트 리소스/PV 잔여 0·운영 설정/Secret 동일 |
| S4 | 11:47 / `01a1f1b3-c9ee-76a2-a191-eab02780a573` | 테스트 워크로드·DB·Secret·인덱스·볼륨 정리·운영 설정 동일 |
| S5 | 11:58 / `01a1f1be-2ac1-78b3-9eb5-2c5c147bcd93` | 임시 DROP 제거·UFW 규칙 동일·타이머 0·테스트 리소스 제거 |
| S6 | 12:12 / `01a1f1ca-409b-79a1-8e55-70e6fc83a483` | 테스트 Job/Pod 잔여 0·운영 setup/kb-ingest Complete·KB 121개 보존 |
| S7 | Actions / RUNBOOK 7단계 | 새 SHA 배포·고장 이미지 실패·48초 복구·외부 23/23 HTTP 200 |
| S8 | 14:18 이후 추가 실습 / [Actions 44464284446](https://github.com/leedongwon9812/edr-ai-triage-lab1/actions/runs/44464284446) | 실제 즉시 종료 이미지의 CrashLoop·undo, packages 쓰기 권한 제거·대문자 이름 거부 재현. 임시 브랜치/리소스/이미지 정리·운영 설정 동일 |

#### 1단계 · 서버 준비와 첫 Deployment

| ID / 고장 | 예상 증상 | 실제 결과·비교 | 처음 확인할 곳 | 복구·원복 / 근거 |
| --- | --- | --- | --- | --- |
| 1-1 이미지 태그 오타 | ErrImagePull·ImagePullBackOff | **일치.** 테스트 Deployment의 존재하지 않는 태그 → not found·ImagePullBackOff | `describe pod <실패 Pod>` Events | 정상 태그 복원 후 `RESTORED_TAG HTTP 200`. 테스트 리소스 정리. S1; RUNBOOK의 이전 `[1-1]`도 별도 근거 |
| 1-2 private 이미지 인증 제거 | unauthorized·이미지 pull 실패 | **일치.** anonymous token 조회 401 Unauthorized → ImagePullBackOff. 게시 권한 403과 별개 | Pod Events·imagePullSecrets 참조/존재 | 인증 복원 후 HTTP 200. 운영 pull 인증은 유지. S1 |
| 1-3 targetPort 불일치 | Pod 정상이어도 접속 실패 | **일치.** 수신 포트 8000에 Service targetPort=8001 → Pod Running/Ready·Connection refused | Service targetPort·실제 수신 포트·EndpointSlice | targetPort=8000 복원 후 HTTP 200. containerPort 선언만 바꾼 실험이 아님. S1 |
| 1-4 kubeconfig server=127.0.0.1 | 노트북에서 connection refused | **일치.** 임시 파일의 `https://127.0.0.1:6443` → exit 1·actively refused | `kubectl config view --minify`의 server; raw 인증 정보 출력 금지 | 임시 파일 삭제·정상 kubeconfig로 edr-team1 Ready, `TEMP_CONFIG_FILES 0`. S1 |

#### 2단계 · OpenSearch StatefulSet

| ID / 고장 | 예상 증상 | 실제 결과·비교 | 처음 확인할 곳 | 복구·원복 / 근거 |
| --- | --- | --- | --- | --- |
| 2-1 vm.max_map_count=65530 | bootstrap 실패·CrashLoopBackOff | **조건 명시.** 테스트 Pod에 bootstrap 강제 검사를 적용해 CrashLoopBackOff·is too low 확인. single-node 기본에서는 경고만 날 수 있음 | OpenSearch 로그·`logs --previous`, `sysctl vm.max_map_count` | 262144 복원 후 테스트 Pod Ready·PVC marker 보존. 영구 파일 해시 동일·타이머 제거. S2 |
| 2-2 heap 2g·limit 2Gi | OOMKilled | **일치.** 실제 종료 reason=OOMKilled·exitCode=137 | Pod state/Last State·Events | 테스트 heap 512m 복원 후 Ready. S2 |
| 2-3 StorageClass 오타 | PVC/Pod Pending | **일치.** local-path-drill-typo → StorageClass not found·unbound PVC·FailedScheduling | `describe pvc` → `describe pod` | 테스트 리소스를 정상 StorageClass로 재생성 → Bound·Ready. 운영 PVC 유지. S2; 이전 RUNBOOK `[2-3]`과 별도 실습 |
| 2-4 requests.memory=64Gi | Pending·Insufficient memory | **일치.** 테스트 Pod Pending·FailedScheduling·Insufficient memory | Pod Events·노드 allocatable/예약 requests | 요청량 복원한 테스트 Pod Ready. S2 |
| 2-5 단일 노드 replica=1 | yellow·미할당 복제본 | **일치.** 별도 테스트 클러스터에서 green→yellow·unassigned_shards=1 | `_cluster/health` → `_cat/shards`·index settings | replica=0 → green·미할당 0. 운영의 기존 top_queries yellow는 별개로 유지. S2 |

**범위:** 커널 값은 서버 전체에 일시 변경했고 사용자 승인을 받았다. 강제 검사는 테스트 Pod에만 적용했다. 운영 OpenSearch는 동일 UID·restart 0이었고, 테스트 namespace·Pod·PVC·PV를 정리했다. 운영 KB 121개·PVC·외부 health 200을 확인했다. 같은 서버의 Pod 재생성 시 데이터 보존도 확인했지만 서버 디스크 소실·백업 복구 검증은 아니다.

#### 3단계 · Postgres·Secret·ConfigMap

| ID / 고장 | 예상 증상 | 실제 결과·비교 | 처음 확인할 곳 | 복구·원복 / 근거 |
| --- | --- | --- | --- | --- |
| 3-1 Secret 삭제 후 API 재시작 | CreateContainerConfigError | **일치.** 테스트 Secret 삭제 → `secret ... not found`·CreateContainerConfigError | Pod Events·envFrom Secret 참조/존재 | Secret 복원 → readyz 200·모든 항목 true. S3 |
| 3-2 초기화 후 Secret 비밀번호만 변경 | password authentication failed | **일치.** 실제 API가 읽는 POSTGRES_DSN의 비밀번호도 잘못 바꿈 → DB 인증 실패·readyz 503 | API/DB 인증 로그·DSN 참조·기존 DB 계정 일치 여부 | 원래 테스트 비밀번호 복원 → readyz 200. 초기화된 DB의 계정 비밀번호가 Secret 변경으로 바뀌지 않음을 확인. S3 |
| 3-3 DSN 호스트 localhost | Connection refused | **일치.** 테스트 API DSN 변경 → 127.0.0.1:5432 Connection refused·readyz 503 | DSN 호스트·Pod 내부 연결 경로 | 테스트 DB Service 이름 복원 → readyz 200. 과거 pg_isready 대조만이 아니라 API 실험까지 확인. S3 |
| 3-4 ConfigMap 변경 후 재시작 생략 | 기존 Pod 환경변수 유지 | **일치.** desired=after인데 같은 Pod의 marker=before 유지 | ConfigMap과 Pod의 비밀 아닌 환경변수 대조 | 재시작 후 after 확인, 이후 테스트 설정을 원래 값으로 복원. S3 |

별도 테스트 API·DB·Secret·PVC/PV를 사용하고 모두 정리했다. 운영 설정·Secret은 전후 동일, 운영 readyz·외부 health는 정상이다. 기존 RUNBOOK의 API 재시작 후 승인/반려 HTTP 200·재호출 409 검증도 별도 근거다. 메모리 모드 재시작 후 410 실험을 수행했다고 확대하지 않는다.

#### 4단계 · 워커·생성기·프로브

| ID / 고장 | 예상 증상 | 실제 결과·비교 | 처음 확인할 곳 | 복구·원복 / 근거 |
| --- | --- | --- | --- | --- |
| 4-1 liveness=readyz + DB 중지 | API 재시작 반복 | **일치.** 테스트 DB 중지 후 liveness 실패·API restart=2·Killing Events | API restart 수·probe Events·DB 상태 | 테스트 DB와 API probe 복원. `API_PROBE_AND_DB_RESTORED`. S4 |
| 4-2 워커 liveness 5초·1회 | 처리 지연 중 재시작 | **조건 명시.** 조사 지연 20초·heartbeat stale=3초를 추가해 HTTP 503·restart=2 재현. 실제 LLM 지연 자체를 측정한 것은 아님 | worker health·heartbeat 경과·probe Events·처리 시간 | 지연 주입·heartbeat·probe를 테스트 기준으로 복원. 운영 stale=180초에서 5초·1회만으로 같은 결과를 보장하지 않음. S4 |
| 4-3 worker replicas=0 | 오류 없이 new 적체 | **일치.** 워커 Pod 0, 생성기 동작 중 new=1→6 증가 | `get deploy worker`, `/stats`·생성기 로그 | 테스트 워커 복원 후 new=0·pending_approval=7, queue drain 확인. 이전 RUNBOOK의 단일 경보 검증보다 추가 관측. S4 |
| 4-4 잘못된 OpenAI 키 | 실제 모델 인증 401·경보 failed | **일치.** 실제 chat/completions에서 401 Unauthorized, 시험 경보 stage4-key가 failed | worker 로그·FAKE_LLM 여부·해당 alert 상태 | 잘못된 키 제거·가짜 LLM 테스트 기준 복원·재시도 후 pending_approval, attempts=2. 이 복구를 유효한 실제 키의 모델 재호출 검증으로 세지 않음. 운영 실제 키는 유지. S4 |
| 4-5 처리 중 worker Pod 삭제 | 작업 재선점·체크포인트 재개 | **조건 명시.** 기본 유예에서는 원래 워커가 완료·attempts=1. 종료 유예 1초로 중단하면 새 worker가 judge 체크포인트부터 이어 처리·attempts 1→2·pending_approval | 같은 alert_id의 worker/owner·lease·attempts·Postgres state·resume 로그 | 시험 lease=20초 조건에서 재개 확인. 이후 지연·lease·종료 유예 복원. 운영 기본 lease의 복구 시간이나 모든 중복 실행 방지를 입증한 것은 아님. S4 |

테스트 워커·생성기·API·DB·Secret·ConfigMap·인덱스·템플릿·PVC/PV를 정리했다. 운영 spec/Secret 비교 동일, 운영 서비스 1/1·PVC Bound·readyz true·KB 121개·외부 health 200을 확인했다. Pod 삭제가 항상 강제 중단이라는 예상은 실제 graceful 종료 결과를 반영해 보완한다.

#### 5단계 · Ingress

| ID / 고장 | 예상 증상 | 실제 결과·비교 | 처음 확인할 곳 | 복구·원복 / 근거 |
| --- | --- | --- | --- | --- |
| 5-1 Ingress host 오타 | 404 page not found | **일치.** 별도 테스트 Ingress의 host 변경 → 기존 host 요청 404, 잘못 설정된 새 host 요청은 200 | DNS·TCP 80 → Ingress host/path | 정상 host 복원 → 200. 운영 Ingress 유지. S5 |
| 5-2 Service selector 오타 | 안내는 endpoint 없음·502 | **예상과 다름.** 실제 endpoint=[]·HTTP 503 `no available server` | EndpointSlice의 주소/ready·Service selector·Pod labels | selector 복원 → HTTP 200. 당시 Traefik allowEmptyServices=true. S5 |
| 5-3 노트북 IP의 TCP 80 임시 차단 | HTTP 없이 타임아웃 | **일치.** 승인 후 임시 DROP, HTTP 응답 없이 4.0초 timeout. 차단 중 backend 직접 요청은 200 | 외부 TCP/HTTP 검사·임시 DROP 규칙 카운터·UFW 상태 | DROP 제거 후 200, UFW 규칙 동일·복구 타이머/규칙 정리. 공유 가비아 보안 그룹 유지. S5 |
| 5-4 readiness 항상 실패 | 안내는 Running 0/1·502 | **예상과 다름.** Pod Running·Ready 0/1·endpoint ready=false, 외부 HTTP 503. readiness probe는 404로 실패·restart 0 | Pod READY·probe Events·EndpointSlice ready | readiness 복원 후 rollout 성공·HTTP 200. S5 |

테스트 Ingress·Service·Deployment·방화벽 규칙·복구 타이머를 모두 정리했다. 운영 spec 전후 동일·공인 health 200이다. **이 환경의 ‘사용 가능한 backend 없음’은 503**이었으므로 502로 맞추기 위한 Traefik 변경은 하지 않았다. 7단계 Pod 전환 때 관측된 일시적 502와 구분한다.

#### 6단계 · setup·KB 적재 Job

| ID / 고장 | 예상 증상 | 실제 결과·비교 | 처음 확인할 곳 | 복구·원복 / 근거 |
| --- | --- | --- | --- | --- |
| 6-1 Job OpenSearch 주소 오타 | 재시도 후 BackoffLimitExceeded | **조건 명시.** 별도 연결 검사 Job에서 잘못된 DNS 주소 → NameResolutionError, 실패 Pod 2개·BackoffLimitExceeded. KB 전체 적재가 아니라 get_client().cluster.health() 연결 경로를 시험 | 각 시도 Pod 로그·Job conditions·initContainer와 본 작업 구분 | 정상 주소의 새 연결 Job Complete, `OPENSEARCH_CONNECTION_RESTORED yellow`. 운영 클러스터의 기존 yellow와 연결 실패는 구분. S6 |
| 6-2 hi_res·limit 512Mi | OOMKilled | **일치.** 실제 `soc.kb.ingest --dry-run --strategy hi_res` 실행 → 종료 reason=OOMKilled·exitCode=137 | Pod state/Last State·reason/exit code | 정상 기준 fast·4Gi의 새 dry-run Job Complete·PDF 9종/121청크. 파싱 방식과 limit을 함께 복원했으므로 hi_res가 4Gi에서 성공한다는 검증은 아님. S6 |
| 6-3 완료 Job template 수정 후 apply | field is immutable | **일치.** 테스트 Job 완료 후 명령 변경 → exit 1·`spec.template: field is immutable` | apply 오류의 필드·기존 Job 상태 | 거부된 apply는 기존 Job을 변경하지 않음. 테스트 Job 삭제·재생성 후 `immutable-job-version-2` 출력·Complete. S6 |

테스트 Job 5개와 관련 Pod를 제거했고 `TEST_RESOURCES_REMAINING []`를 확인했다. 운영 setup·kb-ingest는 원래 Complete 1/1·spec 동일, KB count=121·테스트 인덱스 없음·운영 readyz true·공인 health 200이었다. 복구 dry-run은 재임베딩·운영 인덱스 재적재가 아니다. Job TTL 후 현재 리소스가 없어져도 이 원본 실행 결과를 근거로 삼는다.

#### 7단계 · CI·배포·롤백

| ID / 고장 | 예상 증상 | 실제 결과·비교 | 처음 확인할 곳 | 복구·원복 / 근거 |
| --- | --- | --- | --- | --- |
| 7-1 시작 직후 죽는 이미지 배포 | rollout 미완료·기존 Pod 서비스 유지 | **일치.** 실제 테스트 이미지를 빌드·노드에 적재해 배포. CMD가 즉시 exit 42 → Error·CrashLoopBackOff·restart 3. rollout 45초 대기는 exit 1·timeout. 정상 이전 Pod는 1/1 유지 | 새 Pod containerStatuses·logs --previous, rollout history·Service health | 먼저 정상 테스트 revision 1로 undo → 새 revision 3, 정상 health 확인까지 1.02초. 테스트 Service·운영 공인 health 각각 19/19 HTTP 200. 이후 테스트 Deployment/Service/Pod·이미지·아카이브 제거. S8 |
| 7-2 workflow의 packages: write 제거 | GHCR push 권한 거부 | **일치(오류 문구 차이).** 임시 브랜치 workflow에서 write를 제거하고 packages: read만 부여. Actions 권한 표시는 Packages: read. 로그인·이미지 빌드 성공 후 실제 push에서 `error from registry: installation not allowed to Write organization package`, exit 1 | [missing_package_write 작업 로그](https://github.com/leedongwon9812/edr-ai-triage-lab1/actions/runs/44464284446/job/135358196368)의 token permissions·실패 step | 임시 workflow 브랜치 삭제. 운영 main의 원래 workflow·packages: write·commit ff435da는 변경 전후 동일. 실패한 테스트 push를 정상 게시로 기록하지 않음. 기존 package Actions 접근 403과 다른 직접 주입 실험. S8 |
| 7-3 이미지 저장소 이름에 대문자 | repository name must be lowercase | **일치.** Actions에서 `ghcr.io/leedongwon9812/EDR-AI-TRIAGE-LAB1:uppercase-drill-...`로 docker build → invalid tag·`repository name must be lowercase`·exit 1 | [uppercase_image_name 작업 로그](https://github.com/leedongwon9812/edr-ai-triage-lab1/actions/runs/44464284446/job/135358195892)의 이미지 이름·빌드 오류 | 소문자 이름으로 별도 로컬 빌드 성공 확인 후 테스트 이미지 삭제. 원격 임시 브랜치 삭제·운영 이미지/워크플로 유지. S8 |

**S8의 실제 실행과 복구 범위:** 즉시 죽는 이미지는 기존 앱 이미지를 기반으로 새 CMD를 넣어 별도로 빌드한 `docker.io/library/stage7-crash-drill:20261119051837`이다. 이미지 이름만 없는 상태나 정상 이미지의 실행 명령을 Pod에서 덮어쓴 시험이 아니다. GHCR 게시 없이 노드 containerd에 임시 import하고 imagePullPolicy=Never로 실행했다. 별도 테스트 Deployment `stage7-process-drill-20261119051837`는 maxUnavailable=0·maxSurge=1, BACKEND=memory·FAKE_LLM=true였고 운영 DB·모델 키를 사용하지 않았다.

```text
FAULT_ROLLOUT_EXIT 1 ... timed out waiting for the condition
lastState.terminated: reason=Error exitCode=42
state.waiting.reason=CrashLoopBackOff restartCount=3
STAGE7_INTENTIONAL_STARTUP_CRASH exit=42
deployment.apps/stage7-process-drill-20261119051837 rolled back
deployment "stage7-process-drill-20261119051837" successfully rolled out
RESTORED_HEALTH HTTP 200 backend=memory
HEALTH_SAMPLES_ALL_200 19
```

복구 1.02초는 **undo 실행부터 정상 rollout·health 확인까지**이며 고장 관찰 45초를 포함한 총시간이 아니다. 기존 Pod가 계속 실행 중이어서 짧은 시간에 복구됐다. 19회는 약 2초 간격의 표본이며 모든 순간·모든 부하의 무중단 보장은 아니다.

권한·이름 시험은 임시 브랜치 `stage7-fault-drill-20261119051837`의 `.github/workflows/ci.yml`에 한정했다. 운영 main·dongwon과 로컬 workflow, Environment 승인 규칙·Secrets는 변경하지 않았다. 두 Actions job과 실행 전체는 **의도한 고장 때문에 failure**로 보존했다. continue-on-error로 성공 처리하지 않았으며 운영 환경으로 배포하는 job도 두지 않았다.

원복 확인: 임시 브랜치 삭제, main commit·workflow 원문 동일 및 packages: write 유지, 테스트 Deployment/Service/Pod 잔여 없음, 서버·로컬 테스트 이미지와 tar 제거를 확인했다. 운영 API·워커·생성기·OpenSearch·Postgres·Service·Ingress·ConfigMap spec 해시는 실습 전후 동일했다. 운영 Deployment 3개는 각각 1/1, PVC 2개는 Bound, readyz의 ready/opensearch/postgres 모두 true, KB 121개·공인 health 200이었다. 운영 이미지 게시·배포 재실행은 필요하지 않았으며 OS·방화벽·운영 Secret은 변경하지 않았다.

**기존 S7 결과도 보존:** 이전의 존재하지 않는 태그 주입은 [44461056039](https://github.com/leedongwon9812/edr-ai-triage-lab1/actions/runs/44461056039)에서 정상 13→고장 14→undo 후 15, 주입~복구 48초·외부 23/23 HTTP 200으로 검증했다. 당시 운영 API imageID는 게시 digest와 일치했고, 기존 리포트·승인 대기 체크포인트도 확인했다. 별도 [정상 배포 44460914705](https://github.com/leedongwon9812/edr-ai-triage-lab1/actions/runs/44460914705)는 success·외부 11/11 HTTP 200이었다. S8 테스트 Deployment revision 1/3과 운영 API revision 13/15를 혼동하지 않는다.

#### 예상하지 못한 문제와 예상이 달랐던 지점

| 사례 | 실제 증상·확인 근거 | 조치·결과 | 다음에 처음 확인할 곳 |
| --- | --- | --- | --- |
| GHCR 계정과 대상 namespace 불일치 | 실제 토큰 계정 ldw1147, 게시 대상 leedongwon9812 → create_package 거부. RUNBOOK 1단계 | 올바른 계정으로 로그인 후 게시 완료. 이어 발생한 별도 denied는 재빌드 후 해결했으나 provenance 단독 원인이라고 확정하지 않음 | 실제 로그인 계정·토큰 권한·대상 namespace. 토큰 값은 출력하지 않음 |
| Actions는 로그인됐지만 GHCR 조회 403 | packages: write가 있어도 기존 패키지 Actions 접근이 막혀 build 실패·deploy 미실행 | 사용자가 Manage Actions access 설정 후 같은 실행 재시도에서 게시 통과 | 실패 step·package 저장소 연결/Actions 접근·workflow 권한 |
| maxUnavailable=0인데 순간 외부 502 | 초기 배포 외부 표본 1회 502, 내부 health/ready는 정상. 경로 갱신과 Pod 종료의 시간차로 추정. RUNBOOK 7단계 | 외부 게이트가 실행 실패 처리·이전 정상 revision 복구. minReadySeconds 10초·preStop 10초·종료 유예 45초 보강 후 정상 배포 11/11·실습 23/23 HTTP 200 | 외부 health 타임스탬프와 Pod 종료·EndpointSlice/Ingress 갱신 시점 대조. Pod Ready만으로 외부 무중단 판단하지 않음 |
| KB Job Complete인데 스캔 PDF 누락 | 첫 dry-run에서 06번 요소·청크 0개. 전체 Job 종료 성공은 문서 내용 성공과 달랐음. RUNBOOK 6단계 | 사용자 승인으로 fast 결과가 비면 OCR fallback. 9종 121청크 적재, 그러나 한글 손상·k10 실패는 남음 | 출처별 청크/텍스트 길이·OCR 결과·해당 문항 검색 결과 |
| 저장돼 있어도 원하는 문서를 못 찾음 | 서버 검색 평가에서 k10·k13·k14 실패, hybrid 18/21. 영어 문서·OCR 문제가 남아 있음 | 적재 성공과 검색/답 품질을 분리. 고도화 후보로 남김; 해결 완료로 표시하지 않음 | 실패 문항별 top-k·출처·원문/청크. 서버 적재 성공 수만 보지 않음 |

#### D3-10 결론과 남은 범위

1. **실습 반영:** 1~6단계 25개 항목과 7단계 추가 3개, 총 28개 항목의 주입·복구 결과를 반영했다. 조건을 추가한 시험과 안내와 달랐던 증상은 각각 명시했다.
2. **예상과 달랐던 점:** 사용 가능한 Ingress backend가 없으면 이 환경에서는 502 대신 503이었다. 워커는 기본 종료 유예에서 기존 프로세스가 완료했고, 1초 유예 중단에서만 새 워커 재개를 관측했다. single-node OpenSearch의 커널 검사는 강제 검사 조건을 명시해야 한다.
3. **원복 확인:** 1~6단계의 리소스·데이터·임시 설정 정리와 커널 262144·임시 DROP 제거·타이머 정리는 과거 세션 출력으로 확인했다. 이번 7단계 추가 실습은 실제 undo와 리소스·이미지·원격 브랜치 삭제, 운영 설정 동일·서비스 정상을 새로 확인했다.
4. **범위 구분:** 7단계는 기존 image pull 실패뿐 아니라 실제 프로세스 즉시 종료·workflow 쓰기 권한 부족·대문자 이름 거부까지 직접 검증했다. 기존 package 접근 403·외부 502는 별도 장애다. 테스트 환경과 표본 결과를 모든 운영 장애의 무중단 보장으로 확대하지 않는다.
5. **공동 작업:** 개인별 장애 주입·복구 기록을 정리했지만 역할을 바꾼 블라인드 종합 드릴, 진단 후 나눔·교차 리뷰 완료를 대신하지 않는다. 이 공동 작업은 기존 기록상 미완료다.
6. **평가와 분리:** D3-10 문서 보완은 완료했다. D3-8 최종 성능 평가·고도화 효과 측정은 별도이며 이번 표에 새 평가 수치를 채우지 않았다. 이후 발견한 고장은 관측일·원인·복구 근거와 함께 추가한다.

## 셀프 체크

> 🕐 **지금 답하지 않아도 됩니다.** 2일차 인프라 1단계를 시작하기 직전에 짝과 함께 답해 봅니다.

1. 파드가 `Running`인데 서비스가 안 되는 경우 세 가지는?
2. liveness와 readiness가 실패했을 때 쿠버네티스는 각각 무엇을 하나?
3. 404와 502의 차이는?
4. "에이전트 답이 틀렸다"를 어떤 순서로 쪼개 보겠는가?

참고: [Google SRE Book, Ch.12 Effective Troubleshooting](https://sre.google/sre-book/effective-troubleshooting/) · [Kubernetes: Troubleshooting Applications](https://kubernetes.io/docs/tasks/debug/debug-application/) · [Debug Pods](https://kubernetes.io/docs/tasks/debug/debug-application/debug-pods/)
