"""Offline bundle integrity checks without downloading packages."""
import json

import pytest

from ocr_service.scripts import offline_common as offline


def test_wheelhouse_rejects_corruption_and_wrong_python(tmp_path, monkeypatch):
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    wheel = wheelhouse / "example-1.0-py3-none-any.whl"
    wheel.write_bytes(b"example")
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("example==1.0\n", encoding="utf-8")
    lock = wheelhouse / "requirements.lock"
    lock.write_text("example==1.0\n", encoding="utf-8")
    model = tmp_path / "model.onnx"
    model.write_bytes(b"model")
    manifest_path = wheelhouse / "manifest.json"
    manifest = {
        "target": offline.target_info(),
        "requirements_sha256": offline.sha256(requirements),
        "lock_sha256": offline.sha256(lock),
        "wheels": {wheel.name: offline.sha256(wheel)},
        "assets": {"model": offline.sha256(model)},
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(offline, "WHEELHOUSE", wheelhouse)
    monkeypatch.setattr(offline, "REQUIREMENTS", requirements)
    monkeypatch.setattr(offline, "LOCK", lock)
    monkeypatch.setattr(offline, "MANIFEST", manifest_path)
    monkeypatch.setattr(offline, "required_assets", lambda: {"model": model})

    assert offline.verify_manifest()["wheels"] == manifest["wheels"]
    wheel.write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        offline.verify_manifest()
    wheel.write_bytes(b"example")
    manifest["target"]["python"] = "0.0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RuntimeError, match="does not match this Python"):
        offline.verify_manifest()
