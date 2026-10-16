#!/usr/bin/env bash
# Remote end-to-end check for the Render deployment (M4).
#
#   BASE_URL=https://newnews-t54x.onrender.com ADMIN_API_KEY=... ./scripts/remote_e2e.sh
#
# Proves the *outer* path: readiness → client mint → ingest → worker stages →
# SSE/feed — no localhost anywhere. Needs the worker service running for the
# pipeline status to advance past `received`.
set -euo pipefail

BASE_URL=${BASE_URL:?set BASE_URL, e.g. https://newnews-t54x.onrender.com}
ADMIN_API_KEY=${ADMIN_API_KEY:?set ADMIN_API_KEY to the same value as the server env var}

py() { python3 -c "$1"; }
step() { printf '\n== %s\n' "$*"; }

step "readiness (remote DB reachable)"
curl -sf "$BASE_URL/readyz" | grep -q '"ready"' \
  && echo " ok — ready" \
  || { echo " FAIL — /readyz not ready"; exit 1; }

step "mint a demo client (admin)"
CLIENT_JSON=$(curl -sf -X POST "$BASE_URL/api/v1/clients" \
  -H "X-Admin-Key: $ADMIN_API_KEY" -H "Content-Type: application/json" \
  -d "{\"name\":\"remote-e2e $(date +%s)\"}")
KEY=$(printf '%s' "$CLIENT_JSON" | py 'import sys,json;print(json.load(sys.stdin)["api_key"])')
echo " client key acquired (nn_…)"

step "ingest a text item (body carries the run stamp so dedupe treats reruns as new)"
STAMP=$(date +%s)
ID=$(curl -sf -X POST "$BASE_URL/api/v1/items" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d "{\"body\":\"Kathmandu, report $STAMP — The cabinet approved flood relief worth 200 million rupees for six districts, ministers said on Tuesday. Construction and distribution work begins next month.\",\"source_key\":\"remote-e2e-$STAMP\"}" \
  | py 'import sys,json;print(json.load(sys.stdin)["id"])')
echo " item $ID"

step "wait for the pipeline (requires the worker service)"
STATUS=""
for i in $(seq 1 45); do
  STATUS=$(curl -sf "$BASE_URL/api/v1/items/$ID" -H "Authorization: Bearer $KEY" \
    | py 'import sys,json;print(json.load(sys.stdin)["status"])')
  printf ' t+%02ds: %s\n' "$((i * 2))" "$STATUS"
  case "$STATUS" in eligible|delivered|needs_review|failed|duplicate) break ;; esac
  sleep 2
done

step "SSE stream (2 s window)"
timeout 2 curl -sN "$BASE_URL/api/v1/events" -H "Authorization: Bearer $KEY" | head -c 400 || true
echo

step "pull feed"
curl -sf "$BASE_URL/api/v1/news" -H "Authorization: Bearer $KEY" | head -c 300
echo

case "$STATUS" in
  eligible|delivered)
    echo; echo "PASS — remote pipeline reached '$STATUS' end-to-end" ;;
  needs_review)
    echo; echo "PASS — AI uncertain path works remotely ('needs_review'; approve via /api/v1/review)" ;;
  *)
    echo; echo "FAIL — status='${STATUS:-unknown}' (worker service not running? check its logs)"
    exit 1 ;;
esac
