#!/usr/bin/env bash
set -euo pipefail
BASE_URL="${1:-${NLLW_API_URL:-http://127.0.0.1:8765}}"
TOKEN="${NLLW_API_TOKEN:-}"
AUTH=()
if [[ -n "$TOKEN" ]]; then
  AUTH=(-H "Authorization: Bearer $TOKEN")
fi
curl -fsS "$BASE_URL/health" | python3 -m json.tool
curl -fsS "$BASE_URL/translate" \
  "${AUTH[@]}" \
  -H 'Content-Type: application/json' \
  -d '{"text":"how are you","src":"auto","dst":"auto"}' | python3 -m json.tool
