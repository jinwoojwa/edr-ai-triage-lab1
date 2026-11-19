#!/usr/bin/env bash
set -euo pipefail

# Run with kubectl access to the soc namespace. Supply POSTGRES_PASSWORD to
# choose a password; otherwise generate one on first run and reuse it later.
# Secret values stay in process memory and are never written to repository files.
namespace=soc
name=soc-app-secrets

if ! command -v kubectl >/dev/null 2>&1; then
  echo 'kubectl is required' >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo 'python3 is required' >&2
  exit 1
fi

if [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
  if kubectl -n "$namespace" get secret "$name" >/dev/null 2>&1; then
    POSTGRES_PASSWORD="$(kubectl -n "$namespace" get secret "$name" -o 'jsonpath={.data.POSTGRES_PASSWORD}' | base64 --decode)"
  else
    POSTGRES_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
  fi
fi
if [[ -z "$POSTGRES_PASSWORD" || "$POSTGRES_PASSWORD" == *$'\n'* || "$POSTGRES_PASSWORD" == *$'\r'* ]]; then
  echo 'POSTGRES_PASSWORD must be nonempty and one line' >&2
  exit 1
fi
export POSTGRES_PASSWORD

# Keep a previously configured API key unless a replacement is supplied.
if [[ -z "${OPENAI_API_KEY:-}" ]] && kubectl -n "$namespace" get secret "$name" >/dev/null 2>&1; then
  OPENAI_API_KEY="$(kubectl -n "$namespace" get secret "$name" -o 'jsonpath={.data.OPENAI_API_KEY}' | base64 --decode)"
fi
export OPENAI_API_KEY="${OPENAI_API_KEY:-}"

python3 -c '
import base64, json, os
from urllib.parse import quote

password = os.environ["POSTGRES_PASSWORD"]
dsn = "postgresql://soc:" + quote(password, safe="") + "@postgres.soc.svc.cluster.local:5432/soc"
data = {
    "POSTGRES_PASSWORD": password,
    "POSTGRES_DSN": dsn,
}
if os.environ.get("OPENAI_API_KEY"):
    data["OPENAI_API_KEY"] = os.environ["OPENAI_API_KEY"]
secret = {
    "apiVersion": "v1", "kind": "Secret",
    "metadata": {"name": "soc-app-secrets", "namespace": "soc"},
    "type": "Opaque",
    "data": {key: base64.b64encode(value.encode()).decode() for key, value in data.items()},
}
print(json.dumps(secret))
' | kubectl apply --server-side --field-manager=soc-secrets -f - >/dev/null

unset POSTGRES_PASSWORD OPENAI_API_KEY
echo 'Secret soc/soc-app-secrets applied (values not shown)'
