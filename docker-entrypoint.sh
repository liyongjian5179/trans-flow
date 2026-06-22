#!/usr/bin/env sh
set -eu

mkdir -p /models/huggingface /models/cache

# For bind-mounted ./model-cache on Linux VPS, the directory may be owned by the
# host user/root. Fix it once so the non-root appuser can write downloaded model
# files. Skip recursive chown on later starts when it is already writable.
if ! gosu appuser sh -c 'test -w /models && test -w /models/huggingface && test -w /models/cache' 2>/dev/null; then
  echo "[transflow] fixing /models permissions for appuser..."
  chown -R appuser:appuser /models
fi

exec gosu appuser "$@"
