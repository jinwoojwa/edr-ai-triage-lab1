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

## 인프라 2단계 산정 대기

아래 워크로드는 아직 서버에서 실행하지 않았으므로 실측 사용량이나 적정 request/limit을 기입하지 않는다. 인프라 2단계 배포 전에 각 설정값을 정하고, 배포 후 `kubectl top` 및 디스크 사용량을 다시 측정한다.

| 워크로드 | 종류 | CPU req | Mem req / limit | 힙 | 현재 근거 |
|---|---|---|---|---|---|
| OS + k3s + Traefik | 시스템 | 해당 없음 | 해당 없음 | - | 위 서버·노드 실측값 |
| opensearch | StatefulSet 예정 | 미정 | 미정 | 미정 | 미배포 |
| postgres | StatefulSet 예정 | 미정 | 미정 | - | 미배포 |
| api | Deployment 1개 | 미설정 | 미설정 | - | 현재 사용량 2m / 97Mi |
| worker | Deployment 예정 | 미정 | 미정 | - | 미배포 |
| generator | Deployment 예정 | 미정 | 미정 | - | 미배포 |
| kb-ingest (일시적) | Job 예정 | 미정 | 미정 | - | 미배포 |
| **합계 / 여유** | | **현재 예약 200m / allocatable 4 CPU** | **현재 예약 140Mi / allocatable 16376036Ki** | - | 디스크 여유 44G; 추가 배포 전 재산정 필요 |

재측정 명령:

```bash
free -h
df -h /
sudo k3s kubectl top nodes
sudo k3s kubectl top pods -A
sudo k3s kubectl describe node edr-team1
```
