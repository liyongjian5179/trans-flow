#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip wheel setuptools
# nllw provides the NLLB/SimulMT bridge. The ctranslate2 extra is optional but
# usually faster/lighter than plain transformers when supported by the package.
python -m pip install 'nllw[ctranslate2]==0.1.6'
echo "Done. In Alfred, type: f :start"
