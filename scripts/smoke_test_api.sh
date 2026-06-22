#!/usr/bin/env bash
set -euo pipefail
BASE_URL="${1:-${NLLW_API_URL:-http://127.0.0.1:18765}}"
API_KEY="${NLLW_API_KEY:-}"
AUTH=()
if [[ -n "$API_KEY" ]]; then
  AUTH=(-H "Authorization: Bearer $API_KEY")
fi
curl -fsS "$BASE_URL/health" | python3 -m json.tool
curl -fsS "$BASE_URL/translate" \
  "${AUTH[@]}" \
  -H 'Content-Type: application/json' \
  -d '{"text":"how are you","src":"auto","dst":"auto"}' | python3 -m json.tool
