# 용량 산정 (16GB 서버 기준)

## 서버 실측: 인프라 1단계

측정 시각: **2026-11-18 17:00 KST**. 대상은 `edr-team1` 단일 노드이며, API 1개만 `BACKEND=memory`로 배포한 상태다. 아래 수치는 서버에서 실행한 명령의 출력이다. OpenSearch와 PostgreSQL은 아직 서버에 배포하지 않았다.

| 항목 | 명령 | 측정 결과 |
|---|---|---|
| CPU | `nproc` | 논리 CPU 4개 |
| 메모리 | `free -h` | 전체 15Gi, 사용 1.2Gi, `available` 14Gi, swap 0B |
| 루트 디스크 | `df -h /` | 전체 48G, 사용 3.7G, 여유 44G, 사용률 8% |
| 노드 자원 | `sudo k3s kubectl top nodes` | CPU 53m(1%), 메모리 1478Mi(9%) |
| 커널 설정 | `sysctl vm.max_map_count` | 262144 |
| 노드 상태 | `sudo k3s kubectl describe node edr-team1` | `Ready=True`, `MemoryPressure=False`, `DiskPressure=False`; allocatable CPU 4, 메모리 16376036Ki |

`free -h`의 `used`와 `kubectl top nodes`의 메모리 수치는 서로 다른 방식으로 계산되므로 직접 비교하거나 합산하지 않는다. 디스크 여유 44G는 측정 당시 값이며, 이미지·데이터·로그가 늘면 줄어든다.

### 실행 중인 Pod 사용량

`sudo k3s kubectl top pods -A` 결과. CPU의 `m`은 밀리코어이고, 메모리의 `Mi`는 메비바이트다.

| 네임스페이스 | Pod | CPU | 메모리 |
|---|---|---:|---:|
| kube-system | coredns | 2m | 72Mi |
| kube-system | local-path-provisioner | 1m | 48Mi |
| kube-system | metrics-server | 4m | 79Mi |
| kube-system | svclb-traefik | 0m | 2Mi |
| kube-system | traefik | 1m | 127Mi |
| soc | api | 2m | 97Mi |

`sudo k3s kubectl describe node edr-team1`의 현재 전체 Pod 자원 예약은 **CPU requests 200m(5%), memory requests 140Mi, memory limits 170Mi**다. 이 예약은 kube-system의 coredns와 metrics-server에 해당한다. `sudo k3s kubectl -n soc describe deployment api`에서 API 1개가 `Available=True`이며, API에는 CPU·메모리 request/limit이 설정되지 않은 것을 확인했다. 따라서 API의 위 2m·97Mi는 **현재 사용량**이고, 향후 부하나 최대 사용량을 뜻하지 않는다.

## 인프라 2단계 자원 배분

2026-11-18 배포 전 서버 재확인: `free -h` 전체 15Gi·`available` 14Gi·swap 0B, `df -h /` 전체 48G·여유 44G, `vm.max_map_count=262144`. 아래 OpenSearch 수치는 **설정값**이며, 다른 미배포 워크로드는 **후속 단계의 잠정 예산**이다. 실측 사용량과 혼동하지 않는다.

| 워크로드 | 종류 | CPU req | Mem req / limit | 힙 | 근거·상태 |
|---|---|---|---|---|---|
| OS + k3s + Traefik | 시스템 | 500m 여유 확보 | 2Gi 여유 확보 | - | 노드 실측 53m / 1478Mi; 예약값 아님 |
| opensearch | StatefulSet 1개 | 500m | 2Gi / 2Gi | 1Gi | 이번 단계 설정; 힙은 limit의 50% |
| postgres | StatefulSet 예정 | 250m | 512Mi / 1Gi | - | 잠정 예산, 미배포 |
| api | Deployment 1개 | 후속 단계 목표 100m | 후속 단계 목표 256Mi / 512Mi | - | 현재는 request/limit 미설정, 실측 2m / 97Mi |
| worker | Deployment 예정 | 250m | 512Mi / 1Gi | - | 잠정 예산, 미배포 |
| generator | Deployment 예정 | 100m | 256Mi / 512Mi | - | 잠정 예산, 미배포 |
| kb-ingest (일시적) | Job 예정 | 250m | 512Mi / 1Gi | - | 잠정 예산, 미배포; 파싱 전략에 따라 재산정 |
| **동시 실행 가정 합계** | | **약 1.95 CPU / 총 4 CPU** | **request·시스템 여유 약 6Gi / limit·시스템 여유 약 8Gi / 총 15Gi** | - | 미래 부하와 Job 동시 실행을 가정한 계획값 |

OpenSearch PVC는 `local-path`·`ReadWriteOnce`·20Gi로 시작한다. 루트 디스크 여유 44G는 Postgres 데이터, 이미지, 로그와 나눠 써야 한다. `local-path`의 요청 용량 20Gi가 실제 파일 사용량에 대한 강제 상한인지는 별개이므로 `df -h /`와 OpenSearch 인덱스 크기를 관찰한다. 현재 StorageClass의 reclaim policy는 `Delete`, volume expansion은 `false`다. PVC 삭제는 영속성 시험에 포함하지 않는다.

### 인프라 2단계 배포 후 실측

**2026-11-18 17:10 KST**, OpenSearch Pod 재생성 뒤 측정했다.

| 항목 | 명령 | 측정 결과 |
|---|---|---|
| 메모리 | 서버 `free -h` | 전체 15Gi, 사용 2.7Gi, `available` 12Gi, swap 0B |
| 루트 디스크 | 서버 `df -h /` | 전체 48G, 사용 6.1G, 여유 42G, 사용률 13% |
| 노드 사용량 | `kubectl top nodes` | CPU 73m(1%), 메모리 2923Mi(18%) |
| OpenSearch Pod | `kubectl -n soc top pods` | CPU 25m, 메모리 1427Mi |
| API Pod | `kubectl -n soc top pods` | CPU 2m, 메모리 97Mi |
| 영속 볼륨 | `kubectl -n soc get pvc` | `data-opensearch-0` Bound, `local-path` 20Gi |

OpenSearch 시작·재시작 직후에는 CPU 1111m 및 1983m도 관측했다. 위 25m는 한 시점의 안정화 후 사용량이며, 피크나 장기 평균이 아니다. 디스크 사용량은 배포 전 3.7G에서 6.1G로 증가했지만 이미지·로그·데이터 중 각 항목의 기여량은 분리 측정하지 않았다. Postgres 등 후속 워크로드를 배포하기 전에 이 실측값으로 예산을 다시 조정한다.

재측정 명령:

```bash
free -h
df -h /
sudo k3s kubectl top nodes
sudo k3s kubectl top pods -A
sudo k3s kubectl describe node edr-team1
```
