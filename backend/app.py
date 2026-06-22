from __future__ import annotations

import os
import time
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    from .lang import LANG_ALIASES, LANG_DISPLAY_NAMES, choose_auto_dst, detect_source_lang, normalize_lang
    from .translator import EngineConfig, NLLWTranslator
except ImportError:  # Allow `python backend/app.py` during local dev.
    from lang import LANG_ALIASES, LANG_DISPLAY_NAMES, choose_auto_dst, detect_source_lang, normalize_lang
    from translator import EngineConfig, NLLWTranslator

STARTED_AT = time.time()


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = env(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(value, minimum)


API_KEY = env("NLLW_API_KEY")
AUTO_TARGET_LANG = normalize_lang(env("NLLW_AUTO_TARGET_LANG", "zho_Hans"))
AUTO_ALT_TARGET_LANG = normalize_lang(env("NLLW_AUTO_ALT_TARGET_LANG", "eng_Latn"))
MAX_TEXT_CHARS = env_int("NLLW_MAX_TEXT_CHARS", 4000)

translator = NLLWTranslator(
    EngineConfig(
        backend=env("NLLW_BACKEND", "transformers"),
        model_size=env("NLLW_MODEL_SIZE", "600M"),
    )
)

app = FastAPI(
    title="TransFlow API",
    description="Docker-friendly HTTP API for NoLanguageLeftWaiting / NLLB translation.",
    version="0.1.0",
)

allowed_origins = [o for o in env("NLLW_CORS_ORIGINS", "*").split(",") if o]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


class TranslateRequest(BaseModel):
    text: str = Field(..., min_length=0, max_length=MAX_TEXT_CHARS)
    src: str | None = Field(default="auto", description="NLLB source language code, alias, or auto")
    dst: str | None = Field(default="auto", description="NLLB target language code, alias, or auto")


class TranslateResponse(BaseModel):
    ok: bool
    translation: str
    validated: str = ""
    buffer: str = ""
    src: str
    dst: str
    detected_src: str
    backend: str
    model_size: str


def require_api_key(authorization: str | None = Header(default=None)) -> None:
    if not API_KEY:
        return
    expected = f"Bearer {API_KEY}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="missing or invalid bearer key")


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "ok": True,
        "uptime_seconds": round(time.time() - STARTED_AT, 3),
        "backend": translator.config.backend,
        "model_size": translator.config.model_size,
        "auth_enabled": bool(API_KEY),
    }


@app.get("/ready", dependencies=[Depends(require_api_key)])
def ready() -> dict[str, object]:
    return {"ok": True, "loaded_models": translator.loaded_models}


@app.get("/languages")
def languages() -> dict[str, object]:
    return {
        "ok": True,
        "aliases": LANG_ALIASES,
        "display_names": LANG_DISPLAY_NAMES,
        "auto_target_lang": AUTO_TARGET_LANG,
        "auto_alt_target_lang": AUTO_ALT_TARGET_LANG,
    }


@app.post("/translate", response_model=TranslateResponse, dependencies=[Depends(require_api_key)])
def translate(req: TranslateRequest) -> TranslateResponse:
    text = req.text.strip()
    detected_src = detect_source_lang(text)
    src_raw = (req.src or "auto").strip()
    dst_raw = (req.dst or "auto").strip()

    src = detected_src if src_raw.lower() == "auto" else normalize_lang(src_raw)
    dst = choose_auto_dst(src, AUTO_TARGET_LANG, AUTO_ALT_TARGET_LANG) if dst_raw.lower() == "auto" else normalize_lang(dst_raw)

    result = translator.translate(text=text, src=src, dst=dst)
    return TranslateResponse(
        ok=True,
        translation=str(result.get("translation", "")),
        validated=str(result.get("validated", "")),
        buffer=str(result.get("buffer", "")),
        src=src,
        dst=dst,
        detected_src=detected_src,
        backend=translator.config.backend,
        model_size=translator.config.model_size,
    )


@app.post("/detect", dependencies=[Depends(require_api_key)])
def detect(payload: dict[str, str]) -> dict[str, object]:
    text = (payload.get("text") or "").strip()
    src = detect_source_lang(text)
    return {"ok": True, "src": src, "dst": choose_auto_dst(src, AUTO_TARGET_LANG, AUTO_ALT_TARGET_LANG)}
