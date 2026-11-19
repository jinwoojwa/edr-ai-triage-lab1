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

## 서버 인프라 3단계: Postgres + Secret + ConfigMap (2026-11-18)

서버 운영체제·UFW·가비아 보안 그룹 설정은 변경하지 않았다. 배포 직전 서버는 `free -h` 전체 15Gi·`available` 12Gi, `df -h /` 전체 48G·여유 42G, swap 0B, `vm.max_map_count=262144`였다. OpenSearch는 `1/1`, API는 memory 모드 `1/1`이었다.

`infra/scripts/secrets.sh`는 서버에서 임의의 48자리 비밀번호를 생성하고 동일한 값으로 `POSTGRES_PASSWORD`와 URL 인코딩된 `POSTGRES_DSN`을 `soc-app-secrets` Secret에 넣었다. 이번에는 `FAKE_LLM=true`라 `OPENAI_API_KEY`를 넣지 않았다. 비밀값은 터미널 출력·저장소 파일·런북에 남기지 않았다. `kubectl -n soc describe secret soc-app-secrets`에서 **키 이름과 길이만** 확인했다. 첫 PowerShell `Get-Content -Raw ... | ssh ... 'sudo bash -s'` 실행은 Secret 적용 뒤 PowerShell 파이프의 끝 CR 때문에 `bash: line 61: $'\r': command not found`로 종료했다. 입력 줄 끝의 CR을 제거하는 `sudo sed -e "s/\r$//" | sudo bash -s`로 다시 실행해 exit code 0을 확인했다. 두 번째 실행은 기존 Secret의 비밀번호를 재사용했고, 이후 Postgres·API가 같은 자격 증명으로 연결됐다. Secret에는 client-side apply의 평문 `last-applied-configuration` 어노테이션을 남기지 않았다.

노트북의 저장소 밖 kubeconfig를 사용한 적용·확인 명령:

```powershell
$k = 'C:\Users\Admin\.kube\edr-team.yaml'
kubectl --kubeconfig $k apply --dry-run=server -f infra/k8s/30-postgres.yaml -f infra/k8s/31-config.yaml -f infra/k8s/11-api.yaml
kubectl --kubeconfig $k apply -f infra/k8s/31-config.yaml -f infra/k8s/30-postgres.yaml
kubectl --kubeconfig $k -n soc rollout status statefulset/postgres --timeout=300s
kubectl --kubeconfig $k -n soc exec postgres-0 -- pg_isready -U soc -d soc
kubectl --kubeconfig $k -n soc exec postgres-0 -- psql -U soc -d soc -Atqc 'select 1'
kubectl --kubeconfig $k apply -f infra/k8s/11-api.yaml
kubectl --kubeconfig $k -n soc rollout status deployment/api --timeout=180s
```

서버 dry-run에서 Postgres Service 2개·StatefulSet·ConfigMap은 `created (server dry run)`, API Deployment는 `configured (server dry run)`이었다. 실제 적용 뒤 `statefulset.apps/postgres 1/1`, `pod/postgres-0 1/1 Running`, `data-postgres-0` PVC `Bound`·`local-path`·10Gi였다. PV 이름은 `pvc-4ae16ef5-ca30-4245-898b-92a2a28ab52e`다. `postgres` Service는 `10.43.165.50:5432`, headless Service는 `clusterIP: None`이고 EndpointSlice는 둘 다 `postgres-0:5432`를 가리켰다. `pg_isready`는 `accepting connections`, SQL `select 1`은 `1`이었다. OpenSearch는 계속 `green`이었다.

API 매니페스트 적용 후 `deployment.apps/api 1/1`이었다. API는 기존 GHCR 이미지 `day2-stage1-8aab319`를 유지하고 ConfigMap·Secret을 `envFrom`으로 받는다. 포트 포워딩한 `/healthz`는 `{"status":"ok","backend":"real"}`, `/readyz`는 HTTP 200 및 `{"ready":true,"opensearch":true,"postgres":true}`였다. `kubectl -n soc logs deploy/api`에는 `Postgres 체크포인터 준비 완료`가 있었고, Postgres의 `pg_tables` 조회에서 `checkpoint_blobs`, `checkpoint_migrations`, `checkpoint_writes`, `checkpoints` 4개를 확인했다. 실제 환경은 `FAKE_LLM=true`, 도구는 `mock`이다.

**API Pod 재시작 후 사람 승인 재개 검증:** 고유 ID `test-stage3-approve-mwluvynv`, `test-stage3-reject-mwluvynv`의 시험 경보 두 건을 `edr-alerts`에 넣었다. 각 `/alerts/{id}/triage`가 `pending_approval`을 반환했고, Postgres `checkpoints`에서 서로 다른 시험 thread 2개를 확인했다. API Pod UID는 재시작 전 `2f3e7047-da38-4387-ad7a-1a7defea1a5d`, `kubectl -n soc rollout restart deployment/api` 후 `343bd06c-1a68-40f2-b753-0a1970844dcc`였다. 새 Pod의 `/readyz`가 모두 `true`인 뒤 두 `/approvals/{id}` 호출은 각각 **HTTP 200**, 승인 `true`·반려 `false`, 경보 상태 `completed`였다. 같은 승인 재호출은 **HTTP 409**였다. 검증 후 두 시험 경보·리포트 문서와 해당 ID의 `checkpoint_writes`, `checkpoint_blobs`, `checkpoints` 행만 삭제했고, 시험 `checkpoints` 잔여 건수는 0이었다. 기존 운영 문서는 삭제하지 않았다.

### [3-3] DSN 호스트를 localhost로 지정 (기술 재현·복구 완료, 짝 진단 후 나눔 대기)

- **증상:** 운영 API 설정을 건드리지 않고 임시 Pod `stage3-dsn-check`에서 `pg_isready -h localhost -p 5432 -U soc -d soc`를 실행하자 `localhost:5432 - no response`, exit code 2였다.
- **확인 명령과 출력:** 같은 Pod에서 `pg_isready -h postgres -p 5432 -U soc -d soc`는 `postgres:5432 - accepting connections`였다. 운영 Postgres Pod도 `1/1 Running`이었다.
- **원인:** Pod 안의 `localhost`는 그 Pod 자신이며 Postgres Service 주소가 아니다.
- **조치:** 임시 Pod를 삭제했다. 운영 API의 `POSTGRES_DSN`은 처음부터 Service 주소를 사용했으며 변경하지 않았다. API `/readyz`의 `postgres=true`를 재확인했다.
- **진단 후 나눔:** 🔍 기록 담당자가 부재 중이어서 공동 진단과 복구 시간 측정은 미완료다. 복귀 후 처음 확인할 명령을 함께 정한다.
- **재발 방지:** DSN 호스트를 `postgres.soc.svc.cluster.local`로 두고 Pod 내부 `pg_isready -h postgres`로 연결 경로를 확인한다.

**배포 후 용량 (17:27 KST):** 서버 `free -h` 사용 2.7Gi·`available` 12Gi, `df -h /` 사용 6.6G·여유 41G였다. `kubectl top nodes`는 68m·2991Mi, Pod는 OpenSearch 19m·1445Mi, Postgres 10m·38Mi, API 2m·77Mi였다. `kubectl describe node`의 전체 Pod 요청은 CPU 1050m·메모리 2956Mi였다. 자세한 설정값과 실측값은 `docs/CAPACITY.md`에 기록했다.

**3단계 결과:** Postgres·Secret·ConfigMap 배포, API 실모드 전환, 체크포인트 테이블 생성, API Pod 재시작 후 승인·반려 HTTP 200 검증은 완료했다. Postgres Pod 자체의 재생성 후 데이터 유지는 이번에 시험하지 않았다. 3-3의 공동 진단 후 나눔은 남아 있다.

## 서버 인프라 4단계: 생성기 + 워커 + 프로브 (2026-11-18)

서버 운영체제·UFW·가비아 보안 그룹 설정은 변경하지 않았다. 배포 전 `free -h`는 전체 15Gi·`available` 12Gi, `df -h /`는 48G 중 41G 여유였고, 노드 사용량은 81m·2978Mi였다. 기존 OpenSearch·Postgres·API는 모두 `1/1`이고 API `/readyz`는 세 항목이 모두 `true`였다. 기존 GHCR 이미지 안에 `soc.worker`, `soc.simulator.run`, `soc.telemetry.tools`가 있는지 Python import로 확인했다. 이미지 기준 커밋 `8aab319` 이후 `src`, Dockerfile, requirements 변경이 없어 기존 태그를 재사용했다.

`infra/k8s/31-config.yaml`의 `TELEMETRY_TOOLS`를 `real`로 변경하고 `11-api.yaml`에 startup(`/healthz`, 5초·30회), liveness(`/healthz`, 10초·3회), readiness(`/readyz`, 10초·3회)를 추가했다. 서버 dry-run은 ConfigMap·API를 `configured`, generator·worker를 `created (server dry run)`으로 검증했다. ConfigMap과 API를 적용한 뒤 `rollout status deployment/api`는 `successfully rolled out`이었다. 새 API Pod는 `1/1 Running`, 재시작 0회이며 `TELEMETRY_TOOLS=real`, `/healthz`는 `backend=real`, `/readyz`는 `{"ready":true,"opensearch":true,"postgres":true}`였다. `kubectl describe deployment api`에서 세 프로브가 각각 설정된 것도 확인했다. `KB_TOOLS=mock`, `FAKE_LLM=true`는 유지했다.

생성기만 먼저 적용해 `rollout status deployment/generator`가 `successfully rolled out`, Pod가 `1/1 Running`·재시작 0회임을 확인했다. 설정은 `SIM_BENIGN_PER_TICK=1`, `SIM_TICK_SEC=10`, `SIM_ATTACK_EVERY_TICKS=6`이다. 워커가 아직 없을 때 생성기 로그는 10초 간격으로 `기록 2건, 새 알림 0건`을 출력했고, `edr-events-2026.11.18` 문서 수가 4건으로 늘었다. `python -m soc.simulator.run --inject credential_dump --host WS-007`을 생성기 Pod에서 실행한 결과는 **기록 3건, 새 알림 1건**이었다. 경보 `al-08a33a91890c`는 `status=new`, 근거 `event_id=evt-20ce37-00000002`였고 이 이벤트 문서가 실제 OpenSearch에 존재함을 확인했다. API `/stats`는 이때 `new=1`이었다.

이어서 `41-worker.yaml`을 적용했다. 워커는 GHCR의 같은 이미지를 `python -m soc.worker`로 실행하고 9100번 `/healthz`·`/metrics`를 제공한다. startup은 10초·30회, liveness는 30초·3회, `HEARTBEAT_STALE_SEC=180`, 종료 유예는 240초다. rollout은 `successfully rolled out`, Pod는 `1/1 Running`·재시작 0회였다. `/healthz`는 `heartbeat 0s ago`, `/metrics`는 `soc_worker_pending_approval 3`, `soc_worker_failed 0`이었다. API `/stats`는 `new=0`, `pending_approval=3`, `failed=0`으로 바뀌었다.

경보 `al-08a33a91890c`는 `pending_approval`, `attempts=1`, `worker=worker-866f9c8f5d-fp7lm`이 됐다. 리포트의 `approval_request`는 판정 `malicious`, 근거 `evt-20ce37-00000001`·`evt-20ce37-00000002`, 권고 `isolate_host`·`reset_password`·`collect_forensics`를 담았다. 두 근거 ID 모두 OpenSearch의 실제 이벤트 문서로 조회했다. Postgres `checkpoints`에서 이 경보의 `thread_id` 행 8개를 확인했다. **위험 조치가 실행된 것은 아니며 사람 승인을 기다리는 상태**다. 플레이북 source는 mock 검색의 응답이므로 실제 KB 적재·검색 품질을 증명하지 않는다.

### [4-3] 워커 0개로 축소 (기술 재현·복구 완료, 짝 진단 후 나눔 대기)

- **증상:** `kubectl -n soc scale deployment/worker --replicas=0` 후 Deployment는 `0/0`, 워커 Pod는 없었다. 생성기는 계속 동작했다.
- **확인 명령과 출력:** 생성기 Pod에서 `credential_dump --host WS-008`을 주입하자 기록 3건·새 경보 1건이 만들어졌다. 경보 `al-f75e6b7d790d`는 `status=new`, API `/stats`는 `new=1`, `pending_approval=3`, `failed=0`이었다. Pod 자체의 오류는 없지만 처리 단계가 멈췄다.
- **원인:** `status=new`를 가져갈 워커 복제본이 0개였다.
- **조치:** `kubectl -n soc scale deployment/worker --replicas=1`로 복구했다. rollout은 `successfully rolled out`, 새 워커 Pod는 `1/1 Running`·재시작 0회였다. 위 경보는 `pending_approval`, `attempts=1`로 이동했고 `/stats`는 `new=0`, `pending_approval=6`, `failed=0`이었다. 새 워커 `/healthz`는 200, `/metrics`의 `soc_worker_pending_approval`은 3·`soc_worker_failed`는 0이었다.
- **진단 후 나눔:** 🔍 기록 담당자가 부재 중이라 공동 진단·복구 시간 측정은 미완료다. 복귀 후 첫 확인 명령을 `kubectl -n soc get deploy worker`와 `/stats` 중 무엇으로 정할지 함께 검토한다.
- **재발 방지:** Pod 상태만 보지 말고 Deployment 복제본과 `status=new` 경보 수를 함께 관찰한다. 스케일 0 실험 후 반드시 1로 복구한다.

**측정 당시 (17:44 KST):** API·generator·worker·OpenSearch·Postgres Pod는 모두 `1/1 Running`, 재시작 0회였다. 두 PVC는 `Bound`, OpenSearch 클러스터는 `green`·미할당 샤드 0개였다. `edr-events-*`는 83건, `/stats`는 `new=0`, `pending_approval=6`, `completed=0`, `failed=0`이었다. 서버 `free -h` 사용 2.9Gi·`available` 12Gi, `df -h /` 사용 6.6G·여유 41G, 노드 사용량 132m·3124Mi였다. Pod별 사용량과 예약량은 `docs/CAPACITY.md`에 기록했다. 생성기는 낮춘 속도로 계속 실행 중이므로 이벤트와 승인 대기 경보 수는 이후 증가할 수 있다. 실제로 뒤이은 확인에서 `pending_approval=9`, `failed=0`이었다.

**4단계 결과:** 실제 이벤트 기록 → 경보 생성 → 실제 텔레메트리 도구 조회 → 가짜 LLM 판정 → Postgres 체크포인트와 승인 대기까지 확인했다. 실제 LLM의 판정 품질과 실KB 검색, 사람의 최종 승인·조치 실행은 이번 검증 범위 밖이다. 4-3의 공동 진단 후 나눔은 남아 있다.

## 서버 인프라 5단계: `/healthz` 전용 Ingress (2026-11-18)

**사전 확인:** `Resolve-DnsName soc.1.201.110.16.nip.io -Type A`는 `1.201.110.16`을 반환했고, `Test-NetConnection 1.201.110.16 -Port 80 -InformationLevel Quiet`는 `True`였다. 적용 전 `http://1.201.110.16/healthz`는 404(`404 page not found`)였다. `IngressClass`는 `traefik (default)`이고 기존 Ingress는 없었다. `soc/api` Service는 80번 포트를 열고 EndpointSlice는 API Pod의 `10.42.0.27:8000`을 가리켰다. 내부 API의 `/healthz`는 `{"status":"ok","backend":"real"}`, `/readyz`는 `{"ready":true,"opensearch":true,"postgres":true}`였다.

**적용 명령과 결과 (PowerShell):**

```powershell
$kubeconfig = 'C:\Users\Admin\.kube\edr-team.yaml'
$manifest = 'D:\workspace\03-projects\edr-ai-triage-lab1\infra\k8s\50-ingress.yaml'
kubectl --kubeconfig $kubeconfig apply --dry-run=server -f $manifest
kubectl --kubeconfig $kubeconfig apply -f $manifest
kubectl --kubeconfig $kubeconfig -n soc get ingress api-health -o wide
kubectl --kubeconfig $kubeconfig -n soc describe ingress api-health
Invoke-WebRequest 'http://soc.1.201.110.16.nip.io/healthz' -UseBasicParsing
```

서버 dry-run은 `ingress.networking.k8s.io/api-health created (server dry run)`, 실제 적용은 `ingress.networking.k8s.io/api-health created`였다. Ingress는 `CLASS=traefik`, `HOSTS=soc.1.201.110.16.nip.io`, `PORTS=80`으로 표시됐고, `describe`의 `/healthz` 백엔드는 `api:80 (10.42.0.27:8000)`, 이벤트는 없었다. `ADDRESS=192.168.0.173`은 서버의 내부 주소이며, 외부 호스트의 실제 응답으로 공인 IP 경로를 검증했다. 로컬 `kubectl diff -f $manifest`는 Windows PATH에 `diff` 실행 파일이 없어 실패했다. 이후 서버 dry-run과 실제 응답으로 검증했다.

**외부 검증:** `http://soc.1.201.110.16.nip.io/healthz`는 HTTP 200과 `{"status":"ok","backend":"real"}`을 반환했다. 공인 IP에 `Host: soc.1.201.110.16.nip.io` 헤더를 넣어도 200이었다. 잘못된 `Host: wrong.example`은 404(`404 page not found`)였다. 같은 공개 호스트에서 `/healthz/extra`, `/approvals`, `/docs`, `/dify/retrieval`은 모두 404였다. 따라서 `Exact /healthz`만 라우팅됐다. 배포 전후 기존 API·generator·worker·OpenSearch·Postgres Pod는 모두 `1/1 Running`이었고 PVC 두 개는 `Bound`였다.

**장애 진단과 복구:** 요청 Host를 잘못 지정해 404를 재현했다. DNS A 레코드, TCP 80, Ingress의 `HOSTS`·`PATHS`, Service의 포트·EndpointSlice 순서로 확인한 뒤 올바른 Host로 요청하니 200으로 복구됐다. Ingress를 수정하거나 서버 운영체제·UFW·가비아 보안 그룹을 변경하지 않았다. 🔍 기록 담당자가 부재 중이므로 장애 공동 진단과 교차 검토는 미완료다.

## 인프라 6단계: setup·KB 적재 Job (2026-11-19)

서버의 기존 API·워커·생성기·OpenSearch·Postgres는 모두 재시작 0회로 실행 중이었다. 노트북 Docker 엔진이 꺼져 있어 기존 Docker Desktop을 시작했다. OS·UFW·가비아 보안 그룹·k3s 전역 설정은 변경하지 않았다. 사용자 승인을 받고 로컬 `.env`의 OpenAI 키를 값 노출 없이 기존 `soc-app-secrets`의 `OPENAI_API_KEY`에 추가했다.

`60-setup-job.yaml`, `61-kb-ingest-job.yaml`은 서버 dry-run에서 모두 `created (server dry run)`이었다. setup은 `python -m soc.setup`으로 실행했고, `setup`과 별도 이름 `setup-repeat-20261119` 모두 `Complete`였다. 두 로그는 `인덱스 준비 완료: edr-events-* 템플릿, 알림, 리포트`였다. 기존 리포트 `al-f75e6b7d790d`의 내용·버전이 전후 동일했으며 템플릿 `edr-events`가 존재했다. 서비스가 계속 새 경보를 만들기 때문에 전체 건수 동일 여부는 멱등성 기준으로 사용하지 않았다.

배포 전 서버에는 `kb-*` 인덱스·별칭이 없었다. OpenSearch `yellow`는 `top_queries-2026.11.19-89290`의 복제본 1개 미할당 때문이며 모든 기본 샤드는 `STARTED`였다. 기존 인덱스 설정은 변경하지 않았다. KB 적재는 별도 후보 `kb-playbooks-d3-candidate-20261119`에 수행하며 API·워커의 mock 설정과 연결하지 않는다.

### 6단계 실행 명령 (프로젝트 루트 PowerShell)

```powershell
$kc = 'C:\Users\Admin\.kube\edr-team.yaml'
docker build -f Dockerfile.kb -t ghcr.io/leedongwon9812/edr-ai-triage-lab1-kb:day3-stage6-20261119-ocr .
docker push ghcr.io/leedongwon9812/edr-ai-triage-lab1-kb:day3-stage6-20261119-ocr
kubectl --kubeconfig $kc apply --dry-run=server -f infra/k8s/60-setup-job.yaml -f infra/k8s/61-kb-ingest-job.yaml
kubectl --kubeconfig $kc apply -f infra/k8s/60-setup-job.yaml
kubectl --kubeconfig $kc -n soc wait --for=condition=complete job/setup --timeout=300s
kubectl --kubeconfig $kc -n soc logs job/setup

# 아래 생성 명령은 새 이름일 때만 사용. 이미 실행한 Job은 먼저 상태·로그를 확인한다.
$dry = kubectl --kubeconfig $kc create --dry-run=client -f infra/k8s/61-kb-ingest-job.yaml -o json | ConvertFrom-Json
$dry.metadata.name = 'kb-ingest-dryrun-ocr-20261119'
$dry.spec.template.spec.containers[0].command = @('python','-m','soc.kb.ingest','--dry-run','--show','3')
$dry | ConvertTo-Json -Depth 40 | kubectl --kubeconfig $kc create -f -
kubectl --kubeconfig $kc -n soc logs job/kb-ingest-dryrun-ocr-20261119
# 9종 청크 결과 검토 후 본 적재 실행
kubectl --kubeconfig $kc apply -f infra/k8s/61-kb-ingest-job.yaml
kubectl --kubeconfig $kc -n soc wait --for=condition=complete job/kb-ingest --timeout=1800s
kubectl --kubeconfig $kc -n soc logs job/kb-ingest
```

KB 이미지의 로컬 크기는 4,163,089,047바이트였다. GHCR 게시 digest는 `sha256:27bc9c4b78c7a47263db8a8c7d1aa6bd5bc4a5e79501910bd0a1057e707a6cec`다. 이미지에서 PDF 9개, Unstructured import, OCR 언어 `eng/kor/osd`, `/app/.env` 미포함을 확인했다. 최초 서버 pull에는 수 분이 걸릴 수 있으며 로그 조회가 `PodInitializing`이면 Pod 이벤트에서 `Pulling`인지 먼저 확인한다.

### 6단계 검증 결과와 발견한 문제

첫 dry-run `kb-ingest-dryrun-20261119`는 Job 자체는 92초에 완료됐지만 06번 스캔 PDF가 요소·청크 0개여서 내용 검증은 실패했다. 사용자가 `src/soc/kb/parse.py` 추가 수정을 승인했다. fast 결과에 텍스트가 전혀 없을 때만 `ocr_only`로 재시도하도록 수정했고, 정상 fast 결과 유지와 빈 결과 OCR 재시도를 이미지 안의 mock 검사로 확인했다. 01·09번의 fast 표 복원 경로는 유지됐다. 수정 이미지는 `day3-stage6-20261119-ocr`, digest `sha256:0080aa507e2049fc682ea896591b526ff52c3ed02f1aabe1cfcb38a3b93f7beb`이며 매니페스트도 이 태그를 사용한다.

| 검증 | 실제 결과 |
| --- | --- |
| setup / setup-repeat-20261119 | 각각 6초, Complete 1/1; 기존 리포트 내용·버전 동일 |
| 수정 후 dry-run | `kb-ingest-dryrun-ocr-20261119`, 30초, Complete 1/1; 9종 121개 청크 |
| 본 적재 | `kb-ingest`, 28초, Complete 1/1; 실제 `text-embedding-3-small` 벡터 121건 저장 |
| 검색 검증 | `kb-verify-20261119`, 14초, Complete 1/1; 9종 출처·1536차원·cosinesimil 매핑 확인 |
| Recall@3 (21문항) | 키워드 18/21=0.857, 벡터 16/21=0.762, 하이브리드 18/21=0.857 |

출처별 저장 건수: 01번 14, 02번 2, 03번 3, 04번 2, 05번 2, 06번 1, 07번 2, 08번 3, 09번 92개. `_refresh` 후 실제 count 121개를 확인했다. 후보 인덱스는 복제본 0개, 원본 데이터 크기는 측정 당시 3,300,652바이트였다.

검색 검증 Job은 본 적재 매니페스트의 이미지·환경변수를 재사용하고, 프로젝트의 `search_playbook`, `rag_eval.load_questions`, `rag_eval.evaluate`를 직접 호출했다. `rag_eval`의 기본 QUESTIONS 경로는 이미지에서 `/app/src/data/kb/...`로 해석되므로 검증 시 `load_questions(Path('/app/data/kb/eval_questions.jsonl'))`로 실제 경로를 명시했다. 평가 코드 파일은 수정하지 않았다. `search_playbook('격리는 누가 승인해?', 3)`은 실제 01번 정책 PDF 1쪽의 청크를 반환했지만, 상위 결과에 헤더·다른 조치 행도 포함됐다. 이 결과만으로 격리 승인권자 답이 정확하다고 판정하지 않는다.

**남은 품질 문제:** OCR로 06번이 저장되었지만 한글이 일부 깨져 원문의 완전한 복원으로 볼 수 없다. 하이브리드 실패 문항은 `k10`(06번 스캔본), `k13`·`k14`(08번 영어 문서)다. 청크 수와 Job Complete는 검색 품질의 대체 지표가 아니다. 파싱·검색 고도화와 최종 답 정확도 평가는 후속 작업이다. PDF FontBBox 경고는 있었지만 Job 종료 오류는 없었다.

**배포 후 상태:** 10:47 KST 기준 기존 5개 서비스 Pod는 모두 1/1 Running·재시작 0회, 두 PVC는 Bound, API `/readyz`의 OpenSearch·Postgres는 모두 true였다. 공인 `/healthz`는 HTTP 200과 `backend=real`이었다. API·워커 설정은 `FAKE_LLM=true`, `KB_TOOLS=mock`으로 유지되며, 이번 결과는 실제 임베딩 적재·검색 검증이다. 에이전트의 실LLM/실KB 전환과 외부 docs 공개는 수행하지 않았다.

Job은 완료 후 86400초에 자동 정리된다. `kubectl -n soc get jobs`, `kubectl -n soc logs job/kb-ingest`, `kubectl -n soc logs job/kb-verify-20261119`로 TTL 전 결과를 확인한다. Job 삭제 후에도 OpenSearch 후보 인덱스는 남는다. 재적재할 때는 새 Job 이름·새 후보 인덱스를 사용한다. 기록 담당자 교차 리뷰는 미완료다.

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
