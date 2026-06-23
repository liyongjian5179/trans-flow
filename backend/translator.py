"""NLLW translation engine with lazy model loading and per-source model cache."""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)
LEADING_LIST_MARKER_RE = re.compile(r"^\s*(?:[-*•]\s+)+")


@dataclass(frozen=True)
class EngineConfig:
    backend: str = "transformers"
    model_size: str = "600M"
    cache_size: int = 512


class NLLWTranslator:
    def __init__(self, config: EngineConfig) -> None:
        self.config = config
        self._nllw: Any | None = None
        self._models: dict[tuple[str, str, str], Any] = {}
        self._cache: OrderedDict[tuple[str, str, str], dict[str, str | bool | float]] = OrderedDict()
        self._lock = threading.RLock()

    def _import_nllw(self) -> Any:
        if self._nllw is None:
            import nllw  # type: ignore
            self._nllw = nllw
        return self._nllw

    def _model(self, src: str) -> Any:
        key = (self.config.backend, self.config.model_size, src)
        with self._lock:
            if key not in self._models:
                nllw = self._import_nllw()
                logger.info(
                    "loading nllw model backend=%s size=%s src=%s",
                    self.config.backend,
                    self.config.model_size,
                    src,
                )
                self._models[key] = nllw.load_model(
                    src_langs=[src],
                    nllb_backend=self.config.backend,
                    nllb_size=self.config.model_size,
                )
                logger.info("loaded nllw model for src=%s", src)
            return self._models[key]

    @property
    def loaded_models(self) -> list[str]:
        return [f"{backend}:{size}:{src}" for backend, size, src in self._models]

    @property
    def cache_entries(self) -> int:
        with self._lock:
            return len(self._cache)

    def _cache_get(self, key: tuple[str, str, str]) -> dict[str, str | bool | float] | None:
        if self.config.cache_size <= 0:
            return None
        with self._lock:
            cached = self._cache.get(key)
            if cached is None:
                return None
            self._cache.move_to_end(key)
            result = dict(cached)
            result["cache_hit"] = True
            result["elapsed_ms"] = 0.0
            return result

    def _cache_set(self, key: tuple[str, str, str], value: dict[str, str | bool | float]) -> None:
        if self.config.cache_size <= 0:
            return
        with self._lock:
            self._cache[key] = dict(value)
            self._cache.move_to_end(key)
            while len(self._cache) > self.config.cache_size:
                self._cache.popitem(last=False)

    def warmup(self, src_langs: list[str]) -> list[str]:
        loaded: list[str] = []
        for src in src_langs:
            src = (src or "").strip()
            if not src:
                continue
            self._model(src)
            loaded.append(src)
        return loaded

    @staticmethod
    def _text_part(value: Any) -> str:
        """Extract plain text from nllw return values.

        nllw may return strings, TimedText objects, or lists/tuples of TimedText
        objects. Using ``str(value)`` on TimedText returns a debug repr such as
        ``TimedText(text='', start=0.0, end=0)``; for API clients we only want
        the contained text.
        """
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (list, tuple)):
            return "".join(NLLWTranslator._text_part(item) for item in value).strip()
        text = getattr(value, "text", None)
        if text is not None:
            return str(text).strip()
        return str(value).strip()

    @staticmethod
    def _clean_translation(text: str) -> str:
        return LEADING_LIST_MARKER_RE.sub("", text or "").strip()

    @classmethod
    def _join_parts(cls, validated: Any, buffer: Any) -> tuple[str, str, str]:
        validated_s = cls._text_part(validated)
        buffer_s = cls._text_part(buffer)
        translation = (validated_s + (" " if validated_s and buffer_s else "") + buffer_s).strip()
        return validated_s, buffer_s, cls._clean_translation(translation)

    @staticmethod
    def _direct_translation(translator: Any, text: str) -> str:
        backend = getattr(translator, "backend", None)
        simple_translation = getattr(backend, "simple_translation", None)
        if not callable(simple_translation):
            return ""
        _tokens, result = simple_translation(text)
        return NLLWTranslator._clean_translation(NLLWTranslator._text_part(result))

    def translate(self, *, text: str, src: str, dst: str) -> dict[str, str | bool | float]:
        started = time.perf_counter()
        text = (text or "").strip()
        if not text:
            return {"ok": True, "translation": "", "validated": "", "buffer": "", "cache_hit": False, "elapsed_ms": 0.0}

        cache_key = (src, dst, text)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        nllw = self._import_nllw()
        model = self._model(src)
        translator = nllw.OnlineTranslation(model, input_languages=[src], output_languages=[dst])
        try:
            translation = self._direct_translation(translator, text)
            if translation:
                result: dict[str, str | bool | float] = {
                    "ok": True,
                    "translation": translation,
                    "validated": translation,
                    "buffer": "",
                    "cache_hit": False,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                }
                self._cache_set(cache_key, result)
                return result
        except Exception:
            logger.debug("nllw direct translation failed; falling back to streaming", exc_info=True)

        tokens = [nllw.timed_text.TimedText(text)]
        translator.insert_tokens(tokens)
        validated, buffer = translator.process()
        validated_s, buffer_s, translation = self._join_parts(validated, buffer)
        if not translation:
            # Some streaming backends only emit after an explicit empty/final
            # token. This keeps single-shot API calls from returning an empty
            # TimedText buffer when the model has a pending segment.
            try:
                translator.insert_tokens([nllw.timed_text.TimedText("")])
                validated, buffer = translator.process()
                validated_s, buffer_s, translation = self._join_parts(validated, buffer)
            except Exception:
                logger.debug("nllw flush attempt failed", exc_info=True)
        result = {
            "ok": True,
            "translation": translation,
            "validated": validated_s,
            "buffer": buffer_s,
            "cache_hit": False,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        }
        self._cache_set(cache_key, result)
        return result
