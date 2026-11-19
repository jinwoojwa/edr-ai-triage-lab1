#!/usr/bin/env bash
# Day 2 / 1단계: 단일 Ubuntu 서버를 k3s와 이후 OpenSearch 배포에 맞게 준비한다.
# 사용: sudo bash infra/scripts/bootstrap.sh <노트북의 공인 IPv4 주소>
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "root 권한으로 실행하세요: sudo bash $0 <노트북 공인 IPv4>" >&2
  exit 1
fi

admin_ip="${1:-}"
if ! python3 - "$admin_ip" <<'PY'
import ipaddress
import sys

try:
    address = ipaddress.IPv4Address(sys.argv[1])
except ipaddress.AddressValueError:
    raise SystemExit(1)
raise SystemExit(0 if address.is_global else 1)
PY
then
  echo "공인 IPv4 주소 하나를 인자로 주어야 합니다. 6443은 해당 주소에서만 허용합니다." >&2
  exit 1
fi

if ! command -v ufw >/dev/null 2>&1; then
  echo "ufw가 없습니다. 방화벽을 구성할 수 없어 중단합니다." >&2
  exit 1
fi

# SSH가 끊기지 않도록 22번 규칙을 UFW 활성화보다 먼저 넣는다.
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow from "$admin_ip" to any port 6443 proto tcp
# k3s 기본 Pod/Service CIDR. UFW를 유지할 때 k3s 공식 문서가 요구한다.
ufw allow from 10.42.0.0/16 to any
ufw allow from 10.43.0.0/16 to any
ufw default deny incoming
ufw default allow outgoing
ufw --force enable

# OpenSearch가 필요한 최소값을 재부팅 후에도 유지한다.
sysctl_file=/etc/sysctl.d/99-edr-ai-triage.conf
printf 'vm.max_map_count=262144\n' > "$sysctl_file"
sysctl --load "$sysctl_file"

# fstab에 활성 swap 항목이 있는 서버에서도 반복 실행 가능하도록 한다.
if awk '$0 !~ /^[[:space:]]*#/ && NF >= 3 && $3 == "swap" {found=1} END {exit !found}' /etc/fstab; then
  backup="/etc/fstab.edr-ai-triage.$(date -u +%Y%m%dT%H%M%SZ).bak"
  cp -p /etc/fstab "$backup"
  temp_file=$(mktemp)
  trap 'rm -f "$temp_file"' EXIT
  awk '$0 !~ /^[[:space:]]*#/ && NF >= 3 && $3 == "swap" {print "# disabled by edr-ai-triage bootstrap: " $0; next} {print}' /etc/fstab > "$temp_file"
  cat "$temp_file" > /etc/fstab
  echo "fstab의 swap 항목을 비활성화했습니다. 백업: $backup"
fi
swapoff -a

echo "설정 확인:"
ufw status verbose
printf 'vm.max_map_count='; sysctl -n vm.max_map_count
if [[ -n $(swapon --show --noheadings) ]]; then
  echo "swap이 아직 켜져 있습니다." >&2
  exit 1
fi
echo "swap=off"
echo "가비아 보안 그룹에서도 6443/tcp를 ${admin_ip}/32로 제한해야 합니다."
