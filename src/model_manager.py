"""Keep one local GGUF server loaded at a time."""
from __future__ import annotations

import threading

from src.inference import LlamaCppAdapter, PaddleOCRVLAdapter


class LocalModelManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.key = None
        self.model = None

    def get(self, provider: str, settings: dict):
        if provider not in {"qwen", "paddle"}:
            raise ValueError(f"Unknown OCR model: {provider}")
        key = (provider, settings["model_path"], settings["projector_path"], settings["server_path"], settings["max_new_tokens"], settings["context_size"], settings["inference_timeout_seconds"], settings["model_id"])
        with self.lock:
            if self.key == key and self.model is not None and self.model.process.poll() is None:
                return self.model
            if self.model is not None:
                self.model.close()
                self.model = None
                self.key = None
            adapter = PaddleOCRVLAdapter if provider == "paddle" else LlamaCppAdapter
            model = adapter(settings["model_path"], settings["projector_path"], settings["server_path"], settings["max_new_tokens"], settings["context_size"], settings["inference_timeout_seconds"], settings["model_id"])
            self.model, self.key = model, key
            return model
