# NLLW Alfred Translate + Docker Backend

This project provides:

1. A Docker-deployable translation API based on [NoLanguageLeftWaiting](https://github.com/QuentinFuxa/NoLanguageLeftWaiting) / NLLB.
2. An Alfred Workflow client that calls the API with a very short keyword (`f`).

Default routing:

- Any non-Chinese language → Simplified Chinese (`zho_Hans`)
- Chinese → English (`eng_Latn`)

You can override the target in Alfred, e.g. `f ja 你好`, `f fr hello`.


## Download

Download and import the ready-to-use Alfred Workflow:

[Download TransFlow.alfredworkflow](https://github.com/liyongjian5179/trans-flow/raw/main/dist/TransFlow.alfredworkflow)

After importing, set Alfred Workflow **Environment Variables**:

```text
NLLW_API_URL=https://your-translate-domain.example.com
NLLW_API_KEY=your-api-key
```

## Repository layout

```text
backend/                 FastAPI backend wrapping nllw
workflow/                Alfred Workflow source
scripts/package.sh       Build the .alfredworkflow package
scripts/smoke_test_api.sh Test a running backend
docker-compose.yml       Docker Compose deployment
Dockerfile               Backend image
.env.example             Deployment configuration template
```

## Quick start: backend with Docker Compose

```bash
cp .env.example .env
# Edit .env and set a long random NLLW_API_KEY if exposing publicly.
mkdir -p model-cache
docker compose up -d --build
```

Health check:

```bash
curl http://127.0.0.1:18765/health
```

Translate:

```bash
curl -s http://127.0.0.1:18765/translate \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"text":"how are you","src":"auto","dst":"auto"}'
```

The first translation may be slow because the model is downloaded and loaded.
Model cache is persisted in the local bind-mounted directory `./model-cache`, so container restarts/rebuilds will reuse the downloaded files.

## VPS deployment notes

### 1. Deploy service

On your VPS:

```bash
git clone <your-repo-url> trans-flow
cd trans-flow
cp .env.example .env
nano .env
mkdir -p model-cache
docker compose up -d --build
```

### 2. Secure it

If exposed to the Internet, set at least:

```env
NLLW_API_KEY=a-long-random-secret
```

Then either:

- expose `18765` directly with firewall restrictions, or
- put it behind Nginx/Caddy with HTTPS.

Example Nginx reverse proxy:

```nginx
server {
    server_name translate.example.com;

    location / {
        proxy_pass http://127.0.0.1:18765;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Example Caddy reverse proxy:

```caddyfile
translate.example.com {
    reverse_proxy 127.0.0.1:18765
}
```

If you changed `NLLW_HOST_PORT`, use that host port in `proxy_pass` /
`reverse_proxy`.

### 3. Configure Alfred

Import:

```text
dist/TransFlow.alfredworkflow
```

Set Workflow variables:

```text
NLLW_API_URL=https://translate.example.com
NLLW_API_KEY=your-api-key
```

`NLLW_API_URL` is required. The Alfred Workflow is a remote API client only and will not fall back to localhost.

Use:

```text
f how are you      # auto English -> Chinese
f 今天天气很好      # auto Chinese -> English
f ja 你好          # Chinese -> Japanese
f fr hello         # English -> French
```


## Model cache persistence

`docker-compose.yml` uses a host bind mount:

```yaml
volumes:
  - ./model-cache:/models
```

The image sets these cache paths inside the container:

```env
HF_HOME=/models/huggingface
TRANSFORMERS_CACHE=/models/huggingface/transformers
XDG_CACHE_HOME=/models/cache
```

So the first request downloads the model into `./model-cache` on the host. Later `docker compose restart`, `docker compose up -d --build`, or container recreation will reuse the same files and should not download them again.

Operational tips:

```bash
# See cache size
du -sh model-cache

# Backup cache if needed
tar -czf transflow-model-cache.tgz model-cache

# Force re-download by clearing cache
rm -rf model-cache/*
```

Do not commit downloaded model files. `.gitignore` keeps only `model-cache/.gitkeep`.

On Linux VPS, the container starts as root only long enough to ensure `/models` is writable, then runs the API as non-root `appuser`. This avoids permission problems with the host bind mount.

## Backend API

### `GET /health`

Public liveness endpoint. Does not load model.

### `POST /translate`

Requires `Authorization: Bearer ...` if `NLLW_API_KEY` is set.

Request:

```json
{
  "text": "how are you",
  "src": "auto",
  "dst": "auto"
}
```

Response:

```json
{
  "ok": true,
  "translation": "你好吗？",
  "validated": "",
  "buffer": "你好吗？",
  "src": "eng_Latn",
  "dst": "zho_Hans",
  "detected_src": "eng_Latn",
  "backend": "transformers",
  "model_size": "600M"
}
```

### `POST /detect`

Request:

```json
{"text":"こんにちは"}
```

Response:

```json
{"ok":true,"src":"jpn_Jpan","dst":"zho_Hans"}
```

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `NLLW_API_KEY` | empty | Optional bearer key. Strongly recommended on VPS. |
| `NLLW_BACKEND` | `transformers` | nllw backend. `ctranslate2` may be faster if supported. |
| `NLLW_MODEL_SIZE` | `600M` | NLLB model size. Try `1.3B` only with enough RAM/VRAM. |
| `NLLW_PORT` | `18765` | Container listen port. |
| `NLLW_HOST_PORT` | `18765` | Docker Compose host-side published port. |
| `NLLW_AUTO_TARGET_LANG` | `zho_Hans` | Target for non-Chinese input. |
| `NLLW_AUTO_ALT_TARGET_LANG` | `eng_Latn` | Target when input is already Chinese. |
| `NLLW_MAX_TEXT_CHARS` | `4000` | Request text limit. |
| `NLLW_CORS_ORIGINS` | `*` | CORS origins. |

## Build Alfred Workflow

```bash
./scripts/package.sh
```

Output:

```text
dist/TransFlow.alfredworkflow
```

## Run local checks

These checks do not load or download the translation model:

```bash
python3 -m py_compile backend/app.py backend/lang.py backend/translator.py workflow/transflow.py tests/test_transflow_stdlib.py
python3 -m unittest discover -s tests -v
```

## Local development without Docker

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.app:app --host 127.0.0.1 --port 18765
```

Then set Alfred:

```text
NLLW_API_URL=http://127.0.0.1:18765
```

This uses your locally running backend as an explicit remote API URL for Alfred.
