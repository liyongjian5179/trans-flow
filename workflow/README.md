# TransFlow for Alfred / NLLW

A lightweight Alfred Workflow client for [NoLanguageLeftWaiting](https://github.com/QuentinFuxa/NoLanguageLeftWaiting) / NLLB.

## Fast usage

Keyword: `f`

Type the text directly. The workflow auto-detects the source language:

```text
f how are you
f 今天天气很好
f こんにちは
f bonjour tout le monde
```

Default auto routing:

- Any non-Chinese language → Simplified Chinese (`zho_Hans`)
- Chinese → English (`eng_Latn`)

You can override the target with a short keyword right after `f`:

```text
f ja 你好          # auto-detect Chinese, translate to Japanese
f fr hello        # auto-detect English, translate to French
f 韩 how are you   # translate to Korean
f @de 你好         # @ prefix also works
f /ru hello       # / prefix also works
```

You can also force both source and target:

```text
f en>ja how are you
f zh>fr 今天天气很好
f to ja good morning
```

The result list also shows common target-language options; select one to fill the short target keyword automatically.

Press Enter on a result to copy the translation. Hold `Cmd` on the result to copy the original text.

## Backend modes

### Recommended: external backend service

Set Alfred Workflow variables:

```text
NLLW_API_URL=http://127.0.0.1:8765
NLLW_API_TOKEN=optional
```

The backend should implement:

```http
GET /health
POST /translate
```

`POST /translate` body:

```json
{"src":"eng_Latn","dst":"zho_Hans","text":"how are you"}
```

Response:

```json
{"ok":true,"translation":"你好吗？"}
```

### Built-in local service

If `NLLW_API_URL` is empty, the workflow can start its own local service:

```text
f :start
f :stop
f :log
```

Install dependencies in the workflow folder:

```bash
./install_deps.sh
```

The first translation may download/load model files and can take a while.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `NLLW_API_URL` | empty | External backend URL. Empty means use built-in local service. |
| `NLLW_API_TOKEN` | empty | Optional Bearer token. |
| `NLLW_AUTO_TARGET_LANG` | `zho_Hans` | Auto target for non-primary languages. |
| `NLLW_AUTO_ALT_TARGET_LANG` | `eng_Latn` | Target when input is already primary language. |
| `NLLW_BACKEND` | `transformers` | Built-in service backend: `transformers` or `ctranslate2`. |
| `NLLW_MODEL_SIZE` | `600M` | Built-in service model size: `600M` or `1.3B`. |
| `NLLW_PORT` | `8765` | Built-in local service port. |
| `NLLW_REQUEST_TIMEOUT` | `25` | HTTP request timeout in seconds. |

## Language detection

Detection is intentionally fast and local:

- Unicode script detection for Chinese, Japanese, Korean, Cyrillic, Arabic, Hebrew, Hindi, Thai, Greek, Tamil, Telugu, Khmer, Myanmar.
- Lightweight Latin heuristics for English, French, German, Spanish, Portuguese, Vietnamese.
- Ambiguous Latin text falls back to English.

For ambiguous cases, force the direction with `src>dst`.
