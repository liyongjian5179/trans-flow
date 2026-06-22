# TransFlow API Backend

Docker-friendly HTTP backend for Alfred / other clients.

## API

- `GET /health` — liveness, does not load the model
- `GET /ready` — shows loaded model cache, requires API key if configured
- `GET /languages` — aliases and display names
- `POST /detect` — fast local language detection
- `POST /translate` — translate text

### Translate request

```json
{
  "text": "how are you",
  "src": "auto",
  "dst": "auto"
}
```

Defaults:

- non-Chinese → Chinese (`zho_Hans`)
- Chinese → English (`eng_Latn`)

The backend preloads `zho_Hans` and `eng_Latn` by default on startup. Override
with `NLLW_WARMUP_SRCS`, for example:

```env
NLLW_WARMUP_SRCS=zho_Hans,eng_Latn,jpn_Jpan
```

You can force direction:

```json
{"text":"你好","src":"zh","dst":"ja"}
```

### Translate response

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

## Auth

Set `NLLW_API_KEY` to require:

```http
Authorization: Bearer YOUR_API_KEY
```


`/health` remains public for load balancer health checks.
