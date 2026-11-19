# 배포 가이드

대상 저장소: `leedongwon9812/edr-ai-triage-lab1`. 서버: `ubuntu@1.201.110.16`, 단일 k3s 노드, namespace `soc`. 작성일: 2026-11-19. 옆 팀 검증은 미완료다. 아래 준비 절차는 새 환경을 위한 안내이며 기존 DB/PVC를 지우고 재설치하는 명령이 아니다.

## 0. 준비물

- 노트북: Git, Docker, kubectl, SSH 클라이언트. 프로젝트 루트에서 명령을 실행한다.
- 서버: Ubuntu, CPU 4개·메모리 약 16GiB, SSH 접속 키. 자원 배분은 `docs/CAPACITY.md`를 확인한다.
- GHCR 이미지 pull 권한, 실제 모델용 OpenAI 키, Postgres 접속 정보. 값은 Git에 넣지 않는다.
- CI: GitHub Actions 사용 권한, main 게시 권한, `soc` Environment 배포 승인 권한.

## 1. 서버 생성과 초기 설정

기존 bootstrap은 `infra/scripts/bootstrap.sh`다. 서버 OS·방화벽 변경은 사용자 승인이 필요하다. 현재 서버는 swap 해제·`vm.max_map_count=262144` 설정을 사용한다. 다른 사용자가 사용하는 가비아 보안 그룹은 변경하지 않는다. 22·80·443 연결과 UFW의 6443 출발지 제한을 점검한다.

```bash
sudo sysctl vm.max_map_count
swapon --show
sudo ufw status
free -h
df -h /
```

## 2. k3s 설치, 노트북 kubectl 연결

기존 서버에 k3s를 다시 설치하지 않는다. 새 서버라면 공인 IP를 TLS SAN에 포함해 설치하고 서버 주소가 공인 IP인 kubeconfig를 안전하게 전달한다. kubeconfig는 프로젝트 밖에 보관한다. 현재 노트북 파일은 `C:\Users\Admin\.kube\edr-team.yaml`이다.

```powershell
$kc = 'C:\Users\Admin\.kube\edr-team.yaml'
kubectl --kubeconfig $kc get nodes
kubectl --kubeconfig $kc -n soc get pods,pvc
```

## 3. 시크릿

클러스터의 `soc-app-secrets`에는 실제 DB 접속 정보와 `OPENAI_API_KEY`, `ghcr-pull`에는 이미지 다운로드 인증을 등록한다. Secret 값을 화면·문서에 출력하지 않는다. ConfigMap `soc-app-config`는 기존 `31-config.yaml`을 기준으로 한다. envFrom 변경 후에는 대상 앱을 재시작해야 반영된다.

GitHub Environment `soc`는 클러스터 Secret과 별개다. 승인된 배포용 SSH 키를 사용해 다음 네 값을 Environment Secrets에 등록한다.

| 이름 | 값/확인 사항 |
| --- | --- |
| SSH_HOST | `1.201.110.16` |
| SSH_USER | `ubuntu` |
| SSH_PRIVATE_KEY | 승인받은 배포용 개인 키. 본문·로그에 기재하지 않음 |
| SSH_KNOWN_HOSTS | 신뢰한 기존 서버 지문과 대조한 known_hosts 항목 |

Environment required reviewer를 지정해 최초 운영 배포 전에 승인한다. 개인 SSH 키를 임의로 GitHub에 업로드하지 않는다. 전용 공개 키의 서버 등록은 별도 승인 대상이다. `restrict` 옵션을 써도 ubuntu 계정의 명령·sudo 권한 자체를 제한하는 것은 아니다. kubectl 6443을 GitHub runner에 추가 개방할 필요는 없다.

GHCR 게시에는 workflow의 `GITHUB_TOKEN`과 `packages: write`를 사용한다. 기존 package의 Manage Actions access에 이 저장소의 write 권한이 있는지 확인한다. `denied`는 토큰 문자열 교체 전에 package 접근과 workflow 권한을 진단한다.

## 4. 상태 저장 계층 (OpenSearch, Postgres) → 확인 방법

새 환경의 적용 순서는 namespace → Secret 준비 → `20-opensearch.yaml` → `30-postgres.yaml` → `31-config.yaml`이다. 실제 파일명을 먼저 확인하며 기존 서버에서는 조회부터 한다.

```bash
sudo k3s kubectl -n soc get sts,pvc,svc
sudo k3s kubectl -n soc exec postgres-0 -- psql -U soc -d soc -c '\dt'
```

OpenSearch·Postgres StatefulSet이 각각 Ready 1/1, PVC가 Bound이고 체크포인트 테이블이 있어야 한다. OpenSearch yellow는 replica 미할당일 수 있으므로 원인 인덱스를 확인한다. 데이터 손실 여부와 같은 지표로 해석하지 않는다.

## 5. Job (인덱스 초기화, 플레이북 적재) → 확인 방법

기존 `60-setup-job.yaml`·`61-kb-ingest-job.yaml`을 확인하고 setup 완료 후 KB를 적재한다. 파일명이 다르면 `infra/k8s`의 실제 Job 매니페스트를 사용한다. CI 앱 배포는 이 Job을 다시 실행하지 않는다. 완료 Job의 template 수정은 immutable 오류가 나므로 로그 보존 후 해당 Job만 삭제·재생성한다. PVC는 삭제하지 않는다.

```bash
sudo k3s kubectl -n soc get jobs
sudo k3s kubectl -n soc logs job/setup
sudo k3s kubectl -n soc logs job/kb-ingest
```

기존 적재 결과: PDF 9종, 121청크, 1536차원, 활성 후보 `kb-playbooks-d3-candidate-20261119`. TTL 이후 Job이 없어져도 데이터가 삭제된 것은 아니다. 실제 적재·검색 측정은 RUNBOOK의 6단계 기록을 확인한다.

## 6. 앱 (api, worker, generator) → 확인 방법

현재 실서비스 설정은 `BACKEND=real`, `TELEMETRY_TOOLS=real`, `CHECKPOINTER=postgres`, `FAKE_LLM=false`, `KB_TOOLS=real`이다. CI는 격리된 DB·가짜 LLM으로 검증하며 운영 설정을 덮어쓰지 않는다. 자동 배포는 API만 갱신한다. 워커·생성기도 같은 코드를 배포하려면 별도 검증·승인 범위가 필요하다.

```bash
sudo k3s kubectl -n soc get deploy,pods
sudo k3s kubectl -n soc logs deployment/worker --tail=30
sudo k3s kubectl -n soc get endpointslices -l kubernetes.io/service-name=api
```

```powershell
kubectl --kubeconfig $kc -n soc port-forward svc/api 18002:80 --address=127.0.0.1
# 별도 터미널에서
curl.exe -fsS http://localhost:18002/readyz
```

`readyz`는 ready·opensearch·postgres가 모두 true여야 한다. `http://localhost:18002/docs`에서 경보·리포트·승인을 시험한다. 배포로 연결이 끊기면 port-forward를 다시 시작한다. 실제 모델 호출은 비용이 발생하며 단순 health 요청은 모델을 호출하지 않는다.

## 7. Ingress → 확인 방법

```powershell
curl.exe -fsS http://soc.1.201.110.16.nip.io/healthz
```

기대 응답은 `{"status":"ok","backend":"real"}`다. 기존 HTTP Exact `/healthz`는 CI 검증을 위해 유지하고 docs·업무 API는 아래 HTTPS 주소로 공개했다. 실제 발급·적용 결과는 RUNBOOK의 ‘외부 docs/API 공개’에 기록했다.

```powershell
curl.exe -fsS https://soc.1.201.110.16.nip.io/healthz
curl.exe -fsS https://soc.1.201.110.16.nip.io/openapi.json
curl.exe -fsS https://soc.1.201.110.16.nip.io/alerts
```

브라우저에서 `https://soc.1.201.110.16.nip.io/docs`를 연다. 합성 데이터 조회·정상 승인/반려는 키 없이 이용한다. `POST /alerts/{id}/triage`만 Authorize에 전용 키를 입력해야 실행된다. 키 없이 요청하면 401이며 상태 변경·모델 호출은 없다. 서버 키 미설정은 이 route만 503이다. 승인 API는 approval interrupt만 재개하므로 조사·판정 단계 재실행은 409로 막는다. Dify·readyz·임의 경로는 외부에 공개하지 않는다.

전용 키는 OpenAI 키와 다르며 클러스터 `soc-app-secrets`의 `TRIAGE_API_KEY`다. 허가된 관리자는 아래 명령으로 터미널에 값을 표시하지 않고 클립보드에 복사한 뒤 Swagger Authorize에 **키 값만** 붙여 넣는다. 공용 PC에서는 사용 후 클립보드와 브라우저 인증을 지운다. 이 명령의 결과나 키를 채팅·문서에 붙여 넣지 않는다.

```powershell
$keyEncoded = kubectl --kubeconfig $kc -n soc get secret soc-app-secrets -o jsonpath='{.data.TRIAGE_API_KEY}'
[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($keyEncoded)) | Set-Clipboard
Remove-Variable keyEncoded
```

키를 HTTP URL·query·문서·Git에 넣지 않는다. HTTP docs·업무 경로는 HTTPS로 이동하지만 처음부터 HTTPS를 사용한다. HTTP에 이미 보낸 헤더는 리다이렉트가 보호하지 못한다. 단순 유효 키 소지 여부만 검사하므로 사용자별 권한·월별 비용 제한 기능은 없다. 기존 worker의 자동 LLM 호출 비용도 별개로 지속된다.

TLS 구성은 승인 후 cert-manager v1.21.3을 공식 manifest로 설치하고 `51-tls.yaml`의 Issuer·Certificate·Middleware를 적용한다. cert-manager 지원표는 Kubernetes 1.36까지로 현재 k3s 1.37은 공식 지원 범위 밖이며, 이 실습에서 실제 기동·발급을 검증하는 조건으로 승인받았다. 실습 성공을 공식 호환성 보증으로 해석하지 않는다. ACME 이메일은 선택 항목이므로 개인 주소를 임의 등록하지 않았다.

```powershell
kubectl --kubeconfig $kc -n cert-manager get deploy,pods
kubectl --kubeconfig $kc apply -f infra/k8s/51-tls.yaml
kubectl --kubeconfig $kc -n soc wait --for=condition=Ready certificate/soc-public --timeout=300s
# 새 API가 무키 트리아지를 거절하는지 내부 검증한 후 공개
kubectl --kubeconfig $kc apply -f infra/k8s/50-ingress.yaml
kubectl --kubeconfig $kc -n soc get issuer,certificate,ingress
```

신규 Certificate Ready와 신뢰 검증 없이 인증서 경고를 우회하거나 curl -k로 공개 성공을 판정하지 않는다. `soc-public`은 renewBefore=360h·키 rotationPolicy=Always이며 notAfter/renewalTime을 주기적으로 확인한다. TLS 개인 키는 `soc-public-tls`, ACME 계정 키는 `soc-acme-account` Secret에만 저장한다. 사용자 키와도 별개다. 실제 만료·갱신 완료는 당일 기동 검사와 구분한다.

기존 CI/CD는 API Deployment·Service만 적용한다. 50/51 YAML을 main에 push했다고 자동 반영되는 것이 아니므로 위 kubectl 적용과 결과 확인이 필요하다. 공개 전에 인증 이미지부터 배포하며, 문제 발생 시 먼저 `api-public-http`·`api-public-https`만 제거해 health 전용으로 축소한 뒤 이미지 복구를 검토한다. 인증 없는 이전 이미지를 업무 API가 열린 상태로 배포하지 않는다.

## 8. 배포와 롤백

`.github/workflows/ci.yml`: 모든 코드 push/PR은 테스트, trusted main은 테스트 성공 후 SHA 7자리 이미지 게시와 Environment 승인 배포를 수행한다. 문서만 바뀐 push는 실행하지 않는다. SHA 재실행은 동일 이미지의 전체 commit label을 검사해 digest를 재사용한다. SHA 7자리 충돌은 실패시킨다.

CI의 OpenSearch 2.19.0·Postgres 16에 실제 연결한 뒤 Dify 파일만 제외해 pytest를 실행한다. 예상하지 않은 skip 및 Postgres 재개 테스트 누락은 게이트 실패다. test 실패 시 build·deploy는 `needs`로 차단된다. 운영 모델 키를 CI에 주입하지 않는다.

Actions 화면에서 main의 workflow를 선택하고 Run workflow의 `rollback_drill=true`로 고장·복구를 함께 시험한다. Environment 승인 대기 중에는 Review deployments에서 커밋과 이미지를 확인한다. 서버 키·Git 게시 승인까지 끝나기 전에는 실제 실행 완료로 판단하지 않는다.

`deploy.sh`는 API Deployment·Service만 서버 dry-run 후 적용하고, 이미지 tag@digest·Pod imageID·내부 health/ready·외부 health를 검사한다. maxUnavailable=0, maxSurge=1, history 5, deadline 240초, rollout 대기 300초다. minReadySeconds=10·preStop 대기 10초·종료 유예 45초를 둔다. 배포는 GitHub concurrency와 서버 flock으로 직렬화하며 오래된 main 실행은 거부한다. 정상 상태를 기록하기 전에 실패하면 undo하지 않는다. 변경 후 실패하면 기록한 정상 revision으로 undo하며 원래 실행은 실패로 남긴다. 소스 매니페스트의 기본 이미지 대신 workflow가 렌더링한 SHA tag@digest를 적용한다.

고장 실습은 존재하지 않는 새 이미지로 45초간 rollout 실패를 관찰하고, 기존 Ready Pod 유지 확인 후 방금 검증한 정상 revision으로 복원한다. public-health artifact는 2초 간격 표본이며 모든 순간의 무중단을 보증하지 않는다. `deploy.log`에는 이전/신규 revision·실제 digest·복구 시간이 남는다.

```bash
sudo k3s kubectl -n soc rollout history deployment/api
sudo k3s kubectl -n soc get deploy api -o jsonpath='{.spec.template.spec.containers[0].image}'
sudo k3s kubectl -n soc get pods -l app=api -o wide
# 장애 때는 deploy.log의 PREVIOUS_REVISION 실제 숫자를 사용
sudo k3s kubectl -n soc rollout undo deployment/api --to-revision=<정상-revision>
sudo k3s kubectl -n soc rollout status deployment/api --timeout=300s
```

image pull 오류는 실패 Pod describe Events, readiness 실패는 readyz와 DB 연결, SSH 실패는 known_hosts·접속 권한, GHCR denied는 packages 권한부터 확인한다. undo는 Pod template을 되돌리며 Secret·ConfigMap·DB 변경을 복구하지 않는다. 이번 단계에는 DB 마이그레이션이 없다. 안정 revision과 GHCR 이미지를 보존한다.

## 검증 기록

| 단계 | 결과 | 남은 일 |
| --- | --- | --- |
| CI 테스트 | 로컬 및 GitHub runner 실제 격리 DB, Dify 제외 67 passed·0 skipped | 모델 품질 평가는 별도 |
| 정상 자동 배포 | [main push 44460914705](https://github.com/leedongwon9812/edr-ai-triage-lab1/actions/runs/44460914705) success, SHA d202ee9·digest 대조, revision 13, 외부 11/11 HTTP 200 | main은 승인 후 API만 배포 |
| 실패 감지 | 최초 외부 502 1회 감지 → 실행 failure·기존 정상 revision 자동 복구 | 종료 대기 설정을 보강함 |
| 보강 후 롤백 | [44461056039](https://github.com/leedongwon9812/edr-ai-triage-lab1/actions/runs/44461056039) success, 동일 SHA 재사용·고장 이미지 실패·48초 복구·최종 revision 15, 외부 23/23 HTTP 200 | 표본 관측이며 절대 무중단 보장 아님 |
| 데이터 보존 | KB 121개·PVC 2개·기존 리포트·승인 대기 체크포인트 확인, 로컬 docs HTTP 200 | 상세 건수·로그는 RUNBOOK |
| HTTPS 외부 공개 | [5453787 배포](https://github.com/leedongwon9812/edr-ai-triage-lab1/actions/runs/44467318306) success·90 tests·API revision 17, Certificate Ready·정상 CA/SAN 검증 | cert-manager 지원표 밖 k3s 1.37 실습 검증이며 장기 호환 보증 아님 |
| 비용 기준 인증 | 무료 docs·조회·승인/반려 성공, 무키·틀린 키 triage 401, 인증된 실제 모델 1건 200·22.2초 | 트리아지는 Authorize 필요, 전용 키는 위 복사 절차 사용 |
| 인증서 갱신 | 만료 2027-02-17·갱신 예약 2027-02-02 UTC | 예약·Ready 확인이며 미래 갱신 실행을 선검증한 것은 아님 |
| 옆 팀 검증 | 미완료, 검증 팀 미지정 | 옆 팀이 가이드대로 실행하고 질문·해결 기록 |
