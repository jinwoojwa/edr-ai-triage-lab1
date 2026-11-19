#!/usr/bin/env bash
set -Eeuo pipefail

# Runs on the existing k3s server. No Secret or database changes.
# deploy IMAGE DIGEST COMMIT RUN_URL MANIFEST_JSON [true|false]
# rollback REVISION EXPECTED_CURRENT_COMMIT
mode=${1:-}
shift || true
repo=ghcr.io/leedongwon9812/edr-ai-triage-lab1
namespace=soc
deployment=api
K=(sudo -n k3s kubectl -n "$namespace")
changed=false
rollback_revision=

revision() {
  "${K[@]}" get deployment "$deployment" -o json |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["metadata"]["annotations"]["deployment.kubernetes.io/revision"])'
}

verify_current() {
  local target=${1:-} pod
  if [[ -z "$target" ]]; then
    target=$("${K[@]}" get deployment "$deployment" -o json |
      python3 -c 'import json,sys; print(json.load(sys.stdin)["spec"]["template"]["spec"]["containers"][0]["image"])')
  fi
  pod=$("${K[@]}" get pods -l app=api -o json | python3 -c '
import json,sys
target=sys.argv[1]
pods=[p for p in json.load(sys.stdin)["items"]
      if not p["metadata"].get("deletionTimestamp")
      and any(c["name"]=="api" and c["image"]==target for c in p["spec"]["containers"])
      and any(c["name"]=="api" and c["ready"] for c in p["status"].get("containerStatuses", []))]
assert pods, "No Ready API pod for the requested image"
p=pods[0]
if "@sha256:" in target:
    image_id=next(c["imageID"] for c in p["status"]["containerStatuses"] if c["name"]=="api")
    assert image_id.endswith("@"+target.split("@",1)[1]), "Pod digest mismatch"
print(p["metadata"]["name"])
' "$target") || return
  "${K[@]}" exec "$pod" -- python -c '
import json,urllib.request
for path in ("healthz", "readyz"):
    with urllib.request.urlopen("http://localhost:8000/"+path, timeout=8) as r:
        body=json.load(r)
        assert r.status==200
        assert body.get("status")=="ok" if path=="healthz" else all(body.get(k) is True for k in ("ready","opensearch","postgres"))
        print(path, json.dumps(body))
' || return
  printf 'VERIFIED_POD=%s\n' "$pod"
}

rollback_to() {
  local rev=$1
  "${K[@]}" rollout undo "deployment/$deployment" --to-revision="$rev" &&
    "${K[@]}" rollout status "deployment/$deployment" --timeout=300s &&
    verify_current
}

failed() {
  local code=$?
  trap - ERR
  set +e
  echo "DEPLOY_FAILED exit=$code"
  "${K[@]}" get pods -l app=api -o wide
  "${K[@]}" describe deployment "$deployment"
  if [[ "$changed" == true && -n "$rollback_revision" ]]; then
    if rollback_to "$rollback_revision"; then
      echo "ROLLBACK_VERIFIED revision=$rollback_revision"
    else
      echo "ROLLBACK_FAILED revision=$rollback_revision" >&2
    fi
  fi
  exit "$code"
}

if [[ "$mode" == deploy ]]; then
  [[ $# -ge 5 && $# -le 6 ]] || { echo 'Invalid deploy arguments' >&2; exit 2; }
  image=$1 digest=$2 commit=$3 run_url=$4 manifest=$5 drill=${6:-false}
  [[ "$commit" =~ ^[0-9a-f]{40}$ && "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || exit 2
  [[ "$image" == "$repo:${commit:0:7}" && "$drill" =~ ^(true|false)$ ]] || exit 2
  [[ "$run_url" =~ ^https://github.com/leedongwon9812/edr-ai-triage-lab1/actions/runs/[0-9]+$ ]] || exit 2
  desired="$image@$digest"
  # Validate the transferred payload before applying anything.
  python3 - "$manifest" "$desired" "$commit" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1]))
items=obj.get("items", [])
assert obj.get("kind")=="List" and len(items)==2
assert {(d["kind"],d["metadata"]["name"],d["metadata"]["namespace"]) for d in items} == {
    ("Deployment","api","soc"),("Service","api","soc")}
d=next(d for d in items if d["kind"]=="Deployment")
containers=d["spec"]["template"]["spec"]["containers"]
assert len(containers)==1 and containers[0]["name"]=="api" and containers[0]["image"]==sys.argv[2]
assert d["spec"]["template"]["metadata"]["annotations"]["soc.lab/commit"]==sys.argv[3]
assert d["spec"]["strategy"]["rollingUpdate"]=={"maxUnavailable":0,"maxSurge":1}
assert next(d for d in items if d["kind"]=="Service")["spec"].get("type","ClusterIP")=="ClusterIP"
PY
elif [[ "$mode" == rollback ]]; then
  [[ $# -eq 2 && "$1" =~ ^[0-9]+$ && "$2" =~ ^[0-9a-f]{40}$ ]] || exit 2
else
  echo 'Usage: deploy.sh deploy ... | rollback REVISION EXPECTED_COMMIT' >&2
  exit 2
fi

command -v flock >/dev/null
exec 9>/tmp/soc-api-deploy.lock
flock -n 9 || { echo 'Another API deployment holds the lock' >&2; exit 1; }

if [[ "$mode" == rollback ]]; then
  current_commit=$("${K[@]}" get deployment "$deployment" -o json |
    python3 -c 'import json,sys;print(json.load(sys.stdin)["spec"]["template"]["metadata"].get("annotations",{}).get("soc.lab/commit",""))')
  [[ "$current_commit" == "$2" ]] || { echo 'Refusing to roll back a different deployment' >&2; exit 1; }
  rollback_to "$1"
  echo "ROLLBACK_VERIFIED revision=$1"
  exit 0
fi

trap failed ERR
"${K[@]}" rollout status "deployment/$deployment" --timeout=60s
verify_current
rollback_revision=$(revision)
printf 'PREVIOUS_REVISION=%s\n' "$rollback_revision"
"${K[@]}" apply --dry-run=server -f "$manifest"
changed=true
"${K[@]}" apply -f "$manifest"
"${K[@]}" annotate deployment "$deployment" \
  "kubernetes.io/change-cause=commit=$commit run=$run_url" --overwrite
"${K[@]}" rollout status "deployment/$deployment" --timeout=300s
verify_current "$desired"
stable_revision=$(revision)
printf 'DEPLOYED_REVISION=%s\n' "$stable_revision"

if [[ "$drill" == true ]]; then
  # Expected failure: restore this just-verified release, never leave the bad tag.
  rollback_revision=$stable_revision
  start=$SECONDS
  "${K[@]}" set image "deployment/$deployment" "api=$repo:drill-${commit:0:7}-missing"
  if "${K[@]}" rollout status "deployment/$deployment" --timeout=45s; then
    echo 'The deliberately nonexistent image unexpectedly rolled out' >&2
    false
  fi
  "${K[@]}" get pods -l app=api -o wide
  verify_current "$desired"
  rollback_to "$stable_revision"
  verify_current "$desired"
  printf 'DRILL_RECOVERY_SECONDS=%s\n' "$((SECONDS-start))"
  echo 'ROLLBACK_DRILL_PASSED'
fi
echo "DEPLOY_SUCCEEDED image=$desired commit=$commit revision=$(revision)"
