from types import SimpleNamespace

import pytest

import src.model_manager as manager_module


def test_switching_models_closes_previous_server(monkeypatch):
    created = []

    class FakeAdapter:
        def __init__(self, *args):
            self.closed = False
            self.process = SimpleNamespace(poll=lambda: None if not self.closed else 0)
            created.append(self)

        def close(self):
            self.closed = True

    monkeypatch.setattr(manager_module, "LlamaCppAdapter", FakeAdapter)
    monkeypatch.setattr(manager_module, "PaddleOCRVLAdapter", FakeAdapter)
    settings = {"model_path": "a", "projector_path": "b", "server_path": "c", "max_new_tokens": 100, "context_size": 4096, "inference_timeout_seconds": 30, "model_id": "test"}
    manager = manager_module.LocalModelManager()
    first = manager.get("qwen", settings)
    assert manager.get("qwen", settings) is first
    second = manager.get("paddle", settings)
    assert first.closed
    assert second is not first
    assert len(created) == 2
    with pytest.raises(ValueError, match="Unknown OCR model"):
        manager.get("unknown", settings)
    assert not second.closed
