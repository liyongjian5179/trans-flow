"""NLLW translation engine with lazy model loading and per-source model cache."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EngineConfig:
    backend: str = "transformers"
    model_size: str = "600M"


class NLLWTranslator:
    def __init__(self, config: EngineConfig) -> None:
        self.config = config
        self._nllw: Any | None = None
        self._models: dict[tuple[str, str, str], Any] = {}
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

    def translate(self, *, text: str, src: str, dst: str) -> dict[str, str | bool]:
        text = (text or "").strip()
        if not text:
            return {"ok": True, "translation": "", "validated": "", "buffer": ""}

        nllw = self._import_nllw()
        model = self._model(src)
        translator = nllw.OnlineTranslation(model, input_languages=[src], output_languages=[dst])
        tokens = [nllw.timed_text.TimedText(text)]
        translator.insert_tokens(tokens)
        validated, buffer = translator.process()
        validated_s = str(validated or "").strip()
        buffer_s = str(buffer or "").strip()
        translation = (validated_s + (" " if validated_s and buffer_s else "") + buffer_s).strip()
        return {"ok": True, "translation": translation, "validated": validated_s, "buffer": buffer_s}
