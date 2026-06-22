# Agent Notes for TransFlow

This file is for AI coding agents and maintainers working in this repository.

## Project overview

TransFlow provides:

- A Docker-deployable FastAPI translation backend based on `nllw` / NLLB.
- An Alfred Workflow client with the short keyword `f`.

Default routing:

- Non-Chinese input -> Simplified Chinese (`zho_Hans`)
- Chinese input -> English (`eng_Latn`)

## Repository layout

```text
backend/                 FastAPI backend wrapping nllw
workflow/                Alfred Workflow source
scripts/package.sh       Builds dist/TransFlow.alfredworkflow
scripts/smoke_test_api.sh Tests a running backend
tests/                   Lightweight stdlib tests; no model/network required
docker-compose.yml       Docker Compose deployment
Dockerfile               Backend image
.env.example             Deployment configuration template
model-cache/             Host bind mount for downloaded model files
```

## Important implementation notes

- `backend/lang.py` and `workflow/transflow.py` both contain language alias/detection logic.
  Keep them in sync when changing aliases or detection rules.
- Do not introduce control characters into regex strings. Word boundaries should be literal `\\b` in raw strings.
- The workflow can call either:
  - an external backend via `NLLW_API_URL`, or
  - its own local service started with `f :start`.
- The backend lazily loads NLLW models on first translation. Avoid tests that load models unless explicitly needed.
- `dist/TransFlow.alfredworkflow` is a generated artifact.
- `model-cache/` should not contain committed model files.

## Local checks

Run these before handing off changes:

```bash
python3 -m py_compile backend/app.py backend/lang.py backend/translator.py workflow/transflow.py tests/test_transflow_stdlib.py
python3 -m unittest discover -s tests -v
```

These checks intentionally do not load or download translation models.

## Build Alfred Workflow

```bash
./scripts/package.sh
```

Output:

```text
dist/TransFlow.alfredworkflow
```

Rebuild the workflow after changing files under `workflow/`.

## Backend development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.app:app --host 127.0.0.1 --port 8765
```

Then configure Alfred:

```text
NLLW_API_URL=http://127.0.0.1:8765
```

## Docker deployment

```bash
cp .env.example .env
mkdir -p model-cache
docker compose up -d --build
```

Health check:

```bash
curl http://127.0.0.1:8765/health
```

Smoke test a running backend:

```bash
./scripts/smoke_test_api.sh
```

If `NLLW_API_TOKEN` is set, export the same token before running the smoke test.

## Configuration notes

Key environment variables:

- `NLLW_API_TOKEN`: optional bearer token; strongly recommended for public deployments.
- `NLLW_BACKEND`: default `transformers`; `ctranslate2` may be faster if supported.
- `NLLW_MODEL_SIZE`: default `600M`.
- `NLLW_AUTO_TARGET_LANG`: default `zho_Hans`.
- `NLLW_AUTO_ALT_TARGET_LANG`: default `eng_Latn`.
- `NLLW_MAX_TEXT_CHARS`: default `4000`.
- `NLLW_CORS_ORIGINS`: default `*`.

## Stability guidance

- Prefer adding or updating tests in `tests/test_transflow_stdlib.py` for parser/language/config behavior.
- Avoid making model-loading tests part of the default test command.
- Validate generated Alfred JSON by running script-filter commands manually when changing UI behavior, e.g.:

```bash
python3 workflow/transflow.py script-filter 'how are you'
python3 workflow/transflow.py script-filter 'ja 你好'
python3 workflow/transflow.py script-filter ':start'
```

- For public VPS docs, include both Nginx and Caddy examples where reverse proxy guidance is changed.
