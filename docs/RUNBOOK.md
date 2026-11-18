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

## 서버 인프라 1단계 실행 기록 (2026-11-18, 운전 📘)

대상은 `ubuntu@1.201.110.16`의 `edr-team1`이다. SSH 키 파일은 저장소 밖에 두었다. 접속 뒤 `nproc`는 **4**, `free -h`의 전체 메모리는 **15Gi**, `df -h /`의 루트 디스크는 **48G(사용 2.2G, 가용 46G)**였다. Ubuntu는 **24.04**이고 비밀번호 없는 `sudo`가 가능했다. 최초 `swapon --show`는 비었으며, `vm.max_map_count`는 **1048576**, UFW는 **inactive**, k3s는 미설치였다.

`infra/scripts/bootstrap.sh`를 서버에 복사해 `bash -n`과 SHA-256 일치를 확인한 뒤 `sudo bash /tmp/edr-ai-triage-bootstrap-stage1.sh 60.196.24.130`으로 실행했다. `60.196.24.130`은 이 SSH 연결에서 관측된 노트북 공인 IP다. 출력은 UFW `Status: active`, 22/80/443 허용, `6443/tcp ALLOW IN 60.196.24.130`, Pod/Service CIDR 허용, `vm.max_map_count=262144`, `swap=off`였다. 같은 명령을 다시 실행하면 UFW가 `Skipping adding existing rule`을 출력했고 규칙이 중복되지 않았다. `/etc/sysctl.d/99-edr-ai-triage.conf`에 설정을 남겼다.

서버에서 `curl -sfL https://get.k3s.io | sudo sh -s - server --tls-san 1.201.110.16`으로 단일 노드 k3s **v1.37.2+k3s1**을 설치했다. `sudo k3s kubectl get nodes`에서 `edr-team1 Ready`를 확인했다. 노트북의 `Test-NetConnection 1.201.110.16 -Port 6443`도 `True`였다. 가비아 **클라우드 보안 그룹의 규칙 자체는 관리자 웹에서 확인하지 못했다**. 서버 UFW의 6443 허용 출발지는 위 IP 하나다.

앱 이미지를 `ghcr.io/leedongwon9812/edr-ai-triage-lab1:day2-stage1-8aab319`로 빌드해 GHCR에 push했다. 성공한 빌드는 `docker build --platform linux/amd64 --provenance=false --label 'org.opencontainers.image.source=https://github.com/leedongwon9812/edr-ai-triage-lab1' -t ghcr.io/leedongwon9812/edr-ai-triage-lab1:day2-stage1-8aab319 .`이고, push digest는 `sha256:edddea9121a59a39604e16c53acc70fc6cd7fdb2946dcc70692f96dd2d4b62d7`이다. GHCR 패키지는 **private**이다. 저장소 파일에 토큰을 넣지 않고 `soc` 네임스페이스의 `ghcr-pull` Secret에 Docker 자격 증명을 전달했다. 현재 Secret은 `write:packages` 토큰을 사용하므로 이후 **읽기 전용 토큰으로 교체**해야 한다.

서버의 `sudo k3s kubectl apply -f /tmp/10-namespace.yaml`은 `namespace/soc created`, `11-api.yaml`의 서버 dry-run은 Deployment·Service 모두 `created (server dry run)`이었다. 실제 적용 뒤 `sudo k3s kubectl -n soc rollout status deployment/api --timeout=180s`는 `successfully rolled out`을 반환했다. 확인 결과는 아래와 같다.

```text
pod/api-78b65858f9-pqswm   1/1 Running
service/api               ClusterIP  10.43.37.108  80/TCP
endpointslice/api-bkp96   endpoint 10.42.0.10:8000
imageID ghcr.io/leedongwon9812/edr-ai-triage-lab1@sha256:edddea9121a59a39604e16c53acc70fc6cd7fdb2946dcc70692f96dd2d4b62d7
```

로컬 kubeconfig 파일을 추가하지 않기 위해 노트북의 SSH 터널 `-L 18000:127.0.0.1:18000`과 서버의 `sudo k3s kubectl -n soc port-forward svc/api 18000:80 --address 127.0.0.1`을 사용했다. 노트북의 `Invoke-RestMethod http://localhost:18000/healthz` 결과는 **`{"status":"ok","backend":"memory"}`**였다. 포트 포워딩은 확인 후 종료했다. 서버를 `sudo systemctl reboot`로 재부팅한 뒤 SSH가 다시 연결됐고, `edr-team1 Ready`, API `1/1 Running`, `vm.max_map_count=262144`, swap 없음, UFW의 6443 단일 IP 허용이 유지됐다.

추가 파일 생성 승인을 받은 뒤 서버의 `/etc/rancher/k3s/k3s.yaml`을 저장소 **밖** `C:\Users\Admin\.kube\edr-team.yaml`에 복사하고 `server` 주소를 `https://1.201.110.16:6443`으로 바꿨다. 내용과 인증 키는 출력·커밋하지 않았다. 노트북에서 `kubectl --kubeconfig 'C:\Users\Admin\.kube\edr-team.yaml' get nodes -o wide`는 `edr-team1 Ready`를, `-n soc get pods,svc,endpointslices`는 API `1/1 Running`, Service `80/TCP`, endpoint `10.42.0.16:8000`을 반환했다. 노트북의 직접 포트 포워딩 `kubectl --kubeconfig 'C:\Users\Admin\.kube\edr-team.yaml' -n soc port-forward svc/api 18001:80` 뒤 `Invoke-RestMethod http://localhost:18001/healthz`는 **`{"status":"ok","backend":"memory"}`**였고, 확인 후 포트 포워딩을 종료했다.

### GHCR push 중 겪은 장애

- **증상:** 첫 `docker push`에서 `permission_denied: create_package`. 다시 로그인한 뒤에는 레이어가 올라갔지만 마지막에 `denied`가 발생했다.
- **확인 명령과 출력:** Docker 자격 증명에 들어 있는 토큰으로 GitHub `/user`를 조회했다. 처음에는 로그인 계정이 `ldw1147`, 권한은 `write:packages`였고, 대상 패키지 네임스페이스는 `leedongwon9812`였다. 올바른 계정으로 다시 로그인한 뒤 `/user`가 `leedongwon9812`, `write:packages`를 반환했다. 두 번째 실패 직후 패키지에는 태그 없는 버전만 보였다.
- **원인과 조치:** 첫 오류는 **토큰 실제 계정과 GHCR 네임스페이스 불일치**로 확인했다. 두 번째 `denied`는 단일 `linux/amd64` 이미지를 `--provenance=false`로 다시 빌드하자 해결됐지만, provenance가 단독 원인인지는 분리 검증하지 않았다. 최종 push digest를 위에 기록했다.
- **재발 방지:** Docker에 표시되는 사용자 이름만 믿지 말고 토큰의 실제 GitHub 로그인과 권한을 확인한다. 태그가 붙은 최종 manifest와 digest까지 확인한다.

### [1-1] 이미지 태그 오타 (기술 재현·복구 완료, 짝 진단 후 나눔 대기)

- **증상:** `sudo k3s kubectl -n soc set image deployment/api api=ghcr.io/leedongwon9812/edr-ai-triage-lab1:day2-stage1-8aab319-typo` 뒤 `rollout status --timeout=25s`가 `timed out waiting for the condition`을 반환했다. 새 Pod는 `0/1 ImagePullBackOff`였고 기존 정상 Pod는 `1/1 Running`을 유지했다.
- **확인 명령과 출력:** `sudo k3s kubectl -n soc describe pod api-7d7f697f58-fcm9q`의 Events에 `Failed to pull image ...: not found`, `ErrImagePull`, `ImagePullBackOff`가 있었다. 이때 첫 확인 명령은 `kubectl -n soc describe pod <새 Pod>`가 유효했다.
- **원인:** Deployment 이미지 태그 끝의 `-typo`가 GHCR에 존재하지 않았다. pull Secret 문제나 앱 프로세스 오류가 아니었다.
- **조치:** `sudo k3s kubectl -n soc set image deployment/api api=ghcr.io/leedongwon9812/edr-ai-triage-lab1:day2-stage1-8aab319`로 되돌렸다. `rollout status --timeout=120s`가 `successfully rolled out`, 정상 Pod는 `1/1 Running`이었다.
- **진단 후 나눔:** 🔍 기록 담당자가 부재 중이므로 출제자 관찰·짝 나눔과 복구 시간의 공동 측정은 **미완료**다. 복귀 후 이 출력으로 진단자가 걸린 지점과 다음번 첫 명령을 함께 확정한다.
- **재발 방지:** 배포 전 `11-api.yaml`의 태그와 GHCR에 실제 게시된 digest를 대조한다.

**가비아 보안 그룹 확인 (사용자 제공 화면, 2026-11-18):** 서버에 연결된 `edr-k8s-sg`의 인바운드는 TCP 80·443·22와 TCP 6443이 모두 `0.0.0.0/0`이다. 아웃바운드는 모든 프로토콜·포트가 `0.0.0.0/0`으로 허용돼 있다. 이 보안 그룹을 다른 사용자도 사용하므로 **사용자 지시에 따라 클라우드 규칙은 변경하지 않는다**. 따라서 클라우드 보안 그룹 자체는 1단계의 “6443은 내 IP만” 기준을 충족하지 않는다. 이 서버의 UFW는 6443을 현재 SSH 원본 IP `60.196.24.130`으로 제한한다. 노트북 공인 IP가 바뀌면 UFW 허용 출발지도 갱신해야 한다.

**남은 확인:** 공유 보안 그룹의 6443 제한은 적용하지 않는 것으로 결정했다. 필수 깨 보기 **1-1의 기술 재현·복구는 완료**, 🔍 기록 담당자와의 진단 후 나눔은 미완료다. 따라서 D2-10의 공동 완료 표시는 보류한다.

## 서버 인프라 2단계: OpenSearch StatefulSet (2026-11-18)

대상은 기존 `edr-team1`의 `soc` 네임스페이스다. 서버 운영체제·UFW·가비아 보안 그룹 설정은 변경하지 않았다. 배포 직전 서버 `free -h`는 전체 15Gi·`available` 14Gi·swap 0B, `df -h /`는 48G 중 44G 여유, `vm.max_map_count`는 262144였다. 자원 배분과 배포 후 사용량은 `docs/CAPACITY.md`에 기록했다. API는 `BACKEND=memory`를 유지했다.

노트북의 저장소 밖 kubeconfig를 사용해 다음 명령을 실행했다.

```powershell
$k = 'C:\Users\Admin\.kube\edr-team.yaml'
kubectl --kubeconfig $k apply --dry-run=server -f infra/k8s/20-opensearch.yaml
kubectl --kubeconfig $k apply -f infra/k8s/20-opensearch.yaml
kubectl --kubeconfig $k -n soc rollout status statefulset/opensearch --timeout=300s
kubectl --kubeconfig $k -n soc get sts,pods,pvc,svc,endpointslices -o wide
```

서버 dry-run은 Service 2개와 StatefulSet 1개 모두 `created (server dry run)`이었다. 실제 적용 결과는 `service/opensearch created`, `service/opensearch-headless created`, `statefulset.apps/opensearch created`였고 rollout은 `partitioned roll out complete: 1 new pods have been updated...`를 반환했다. `opensearch-0`은 `1/1 Running`, StatefulSet은 `1/1`이었다. `data-opensearch-0` PVC는 `local-path`, 20Gi, `Bound`이며 PV 이름은 `pvc-a245c622-4bf4-4e82-a7a5-145659d6b83a`다. 일반 Service는 `10.43.162.96:9200`, headless Service는 `clusterIP: None`이고 두 EndpointSlice 모두 `opensearch-0:9200`을 가리켰다.

**데이터 유지 검증:** `kubectl -n soc port-forward svc/opensearch 19200:9200` 뒤 `/_cluster/health`는 처음 `green`, 노드 1개, 미할당 샤드 0개였다. 테스트 인덱스 `stage2-persistence-20261118`을 샤드 1개·복제본 0개로 생성하고 고정 ID `probe-1`에 `{"stage":2,"marker":"persistent"}`를 저장했다. `_count`는 **1**이었다. 삭제 전 Pod UID는 `60767456-d621-4c0f-83d0-c182af011769`이었다.

`kubectl --kubeconfig $k -n soc delete pod opensearch-0 --wait=false` 뒤 `rollout status`가 완료됐고, 새 Pod UID는 `340c7bb0-bec4-4a68-a202-2cb0864d516d`로 달라졌다. PVC 이름·PV 이름은 그대로였고 Pod는 다시 `1/1 Running`이었다. 포트 포워딩을 재연결한 후 `/_doc/probe-1`은 `found=true`, `marker=persistent`였으며 `_count`도 **1**이었다. 검증 후 테스트 인덱스만 삭제해 `acknowledged=true`를 확인했다. PVC는 삭제하지 않았다. 이 검증은 **같은 서버에서 Pod가 재생성될 때의 데이터 유지**를 보여 주며, 서버 디스크 손실에 대한 백업 검증은 아니다.

**단일 노드 상태 확인:** 테스트 인덱스를 삭제한 뒤 클러스터가 한때 `yellow`, 미할당 샤드 1개였다. `_cat/indices`와 `_cat/shards`에서 `top_queries-2026.11.18-89289`의 기본 샤드는 `STARTED`, 복제본 1개는 `UNASSIGNED`임을 확인했다. 사용자 승인 후 **해당 인덱스에만** `PUT /top_queries-2026.11.18-89289/_settings`와 `{"index":{"number_of_replicas":0}}`을 적용했다. 응답은 `acknowledged=true`, 이후 `/_cluster/health`는 **`green`**, 노드 1개, 미할당 샤드 0개였다. 이 인덱스 설정 변경은 서버 OS 설정 변경이 아니다. 앞으로 만들어질 다른 `top_queries-*` 인덱스에 같은 복제본 설정이 적용되는지는 확인하지 않았다.

**배포 후 사용량 (17:10 KST):** 서버 `free -h`는 사용 2.7Gi·`available` 12Gi, `df -h /`는 사용 6.1G·여유 42G였다. `kubectl top nodes`는 73m·2923Mi, `kubectl -n soc top pods`는 OpenSearch 25m·1427Mi, API 2m·97Mi였다. 시작·재시작 직후 OpenSearch CPU는 각각 1111m·1983m도 관측했다. 기존 API는 `1/1 Running`이며 포트 포워딩한 `/healthz` 응답은 `{"status":"ok","backend":"memory"}`였다.

### [2-3] StorageClass 이름 오타 (기술 재현·복구 완료, 짝 진단 후 나눔 대기)

- **증상:** 운영 StatefulSet과 별도로 `storageClassName: local-path-typo`인 임시 PVC `stage2-storageclass-check`와 이를 사용하는 임시 Pod를 생성하자 둘 다 `Pending`이 됐다.
- **확인 명령과 출력:** `kubectl -n soc describe pvc stage2-storageclass-check`의 Events는 `ProvisioningFailed: storageclass.storage.k8s.io "local-path-typo" not found`였다. `kubectl -n soc describe pod stage2-storageclass-check`의 Events는 `FailedScheduling: pod has unbound immediate PersistentVolumeClaims`였다.
- **원인:** 클러스터에 존재하지 않는 StorageClass 이름을 지정했다. 실제 StorageClass 이름은 `local-path`다.
- **조치:** 임시 `pod/stage2-storageclass-check`와 `pvc/stage2-storageclass-check`만 삭제했다. 운영 `data-opensearch-0` PVC는 계속 `Bound`, OpenSearch StatefulSet은 `1/1`이었다. 운영 데이터나 PVC는 삭제하지 않았다.
- **진단 후 나눔:** 🔍 기록 담당자가 부재 중이어서 공동 진단과 복구 시간 측정은 미완료다. 복귀 후 `describe pvc`를 첫 확인 명령으로 정할지 함께 검토한다.
- **재발 방지:** 매니페스트 적용 전 `kubectl get storageclass`와 `storageClassName`을 대조한다.

**2단계 결과:** OpenSearch 배포, PVC 바인딩, Pod 삭제 후 데이터 유지, 기존 API 확인은 완료했다. 2-3의 공동 진단 후 나눔은 남아 있다.

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
