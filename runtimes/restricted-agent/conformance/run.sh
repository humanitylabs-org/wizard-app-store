#!/bin/bash
# Restricted-agent conformance run (acceptance test 6). Runs on a Docker host (Thales/colima or Linux).
#
# 1. Plants synthetic canaries (fake host-home file, fake SSH key, fake control-plane secret) on the
#    Docker host and inside a stand-in Agent Service, and mints a fresh agent token and API key.
#    Nothing real is read or copied.
# 2. Starts the runtime with an empty agent home.
# 3. Runs conformance/in_agent.py inside the agent (Hermes' own tool dispatcher, normal tools),
#    outside-in `docker inspect` checks, and an inbound API reachability check.
# 4. Restarts the containers and re-runs; recreates them (home volume kept) and re-runs.
# 5. Writes receipts (synthetic values redacted) and tears everything down, volumes included.
#
# Usage: run.sh <receipts-dir>
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
RECEIPTS="${1:?receipts dir}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$RECEIPTS/$STAMP"
export AGENT_PROJECT="ragent-conf-$(echo "$STAMP" | tr 'A-Z' 'a-z')"
mkdir -p "$OUT"

rand() { python3 -c 'import secrets;print(secrets.token_hex(24))'; }
CANARY="CONFORMANCE-CANARY-$(rand)"
TOKEN="agt_$(rand)"
export CONF_CANARY="$CANARY"
export AGENT_API_KEY="$(rand)$(rand)"
export EDGE_TOKEN_SHA256="$(printf '%s' "$TOKEN" | python3 -c 'import sys,hashlib;print(hashlib.sha256(sys.stdin.read().encode()).hexdigest())')"
export EDGE_UPSTREAM_HOST=fake-service EDGE_UPSTREAM_PORT=8923
export AGENT_INGRESS_BIND="${AGENT_INGRESS_BIND:-127.0.0.1:18642}"

# On colima the Mac home is shared into the VM, so these sit exactly where a careless bind mount
# would expose them. Removed on exit.
HOST_CANARY_DIR="$HOME/.restricted-agent-conformance"
mkdir -p "$HOST_CANARY_DIR/.ssh"
printf 'synthetic host-home file %s\n' "$CANARY" > "$HOST_CANARY_DIR/canary.txt"
printf -- '-----BEGIN SYNTHETIC TEST KEY-----\n%s\n-----END SYNTHETIC TEST KEY-----\n' "$CANARY" > "$HOST_CANARY_DIR/.ssh/id_ed25519"
printf 'WIZARD_SERVICE_SECRET=%s\n' "$CANARY" > "$HOST_CANARY_DIR/controlplane-secrets.env"
HOST_PATHS=$(python3 -c 'import json,sys;h=sys.argv[1];print(json.dumps([h+"/canary.txt",h+"/.ssh/id_ed25519",h+"/controlplane-secrets.env","/tmp/host-home/canary.txt","/tmp/host-home/.ssh/id_ed25519","/tmp/control-plane/secrets.env"]))' "$HOST_CANARY_DIR")

REDACT="$HERE/conformance/redact.py"
DC=(docker compose -f "$HERE/compose.yml" -f "$HERE/conformance/compose.test.yml" -p "$AGENT_PROJECT")
cleanup() {
  "${DC[@]}" logs --no-color > "$OUT/compose-logs.txt" 2>&1 || true
  "${DC[@]}" exec -T fake-service cat /tmp/requests.jsonl > "$OUT/fake-service-requests.jsonl" 2>/dev/null || true
  "${DC[@]}" down -v --remove-orphans > /dev/null 2>&1 || true
  rm -rf "$HOST_CANARY_DIR"
  python3 "$REDACT" "$OUT" "$CANARY" "$TOKEN" "$AGENT_API_KEY" || true
}
trap cleanup EXIT

wait_ready() {
  for _ in $(seq 1 90); do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "http://$AGENT_INGRESS_BIND/health" || true)
    [ "$code" = "200" ] && return 0
    sleep 2
  done
  echo "agent API not ready" >&2; return 1
}

phase() {
  local name="$1"
  wait_ready
  echo "== phase $name"
  "${DC[@]}" exec -T -e CONF_CANARY="$CANARY" -e CONF_TOKEN="$TOKEN" -e CONF_HOST_PATHS="$HOST_PATHS" \
      -e CONF_PHASE="$name" agent /opt/hermes/.venv/bin/python - < "$HERE/conformance/in_agent.py" > "$OUT/$name.json"
  python3 "$HERE/conformance/inspect_check.py" "$AGENT_PROJECT" "$AGENT_INGRESS_BIND" "$AGENT_API_KEY" > "$OUT/$name-inspect.json"
  python3 "$HERE/conformance/summarize.py" phase "$OUT" "$name"
}

echo "project=$AGENT_PROJECT receipts=$OUT"
"${DC[@]}" build -q 2>&1 | tail -3
"${DC[@]}" up -d 2>&1 | tail -3
phase initial
"${DC[@]}" restart 2>&1 | tail -2
phase restart
"${DC[@]}" down 2>&1 | tail -1          # containers removed, home volume kept
"${DC[@]}" up -d 2>&1 | tail -2
phase recreate
python3 "$HERE/conformance/summarize.py" final "$OUT" "$CANARY"
