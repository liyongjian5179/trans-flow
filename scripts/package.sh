#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/workflow"
mkdir -p "$ROOT/dist"
rm -f "$ROOT/dist/TransFlow.alfredworkflow"
zip -r "$ROOT/dist/TransFlow.alfredworkflow" . -x '.venv/*' '__pycache__/*' '*.pyc' >/dev/null
echo "$ROOT/dist/TransFlow.alfredworkflow"
