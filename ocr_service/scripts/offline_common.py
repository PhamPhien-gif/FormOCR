"""Checks shared by wheelhouse creation and offline installation."""
from __future__ import annotations

import hashlib
import json
import platform
import struct
import sys
import sysconfig
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
WHEELHOUSE = SERVICE_ROOT / "wheelhouse"
REQUIREMENTS = SERVICE_ROOT / "requirements.txt"
MANIFEST = WHEELHOUSE / "manifest.json"
LOCK = WHEELHOUSE / "requirements.lock"
MODEL_NAMES = (
    "ch_PP-OCRv5_det_mobile.onnx",
    "en_PP-OCRv5_rec_mobile.onnx",
)
MODEL_ROOT = SERVICE_ROOT / "models" / "rapidocr-ppocrv5-en"
REFERENCE_PDF = SERVICE_ROOT / "assets" / "MOE_FAS_Application_Form.pdf"


def target_info() -> dict[str, str | int]:
    return {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "implementation": platform.python_implementation(),
        "platform": sysconfig.get_platform().lower(),
        "bits": struct.calcsize("P") * 8,
    }


def sha256(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def required_assets() -> dict[str, Path]:
    return {
        "reference_pdf": REFERENCE_PDF,
        **{name: MODEL_ROOT / name for name in MODEL_NAMES},
    }


def verify_manifest() -> dict:
    if not MANIFEST.is_file():
        raise RuntimeError(f"Missing {MANIFEST}. Build the wheelhouse on a connected machine first.")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("target") != target_info():
        raise RuntimeError(f"Wheelhouse target {manifest.get('target')} does not match this Python: {target_info()}")
    if manifest.get("requirements_sha256") != sha256(REQUIREMENTS):
        raise RuntimeError("requirements.txt changed after the wheelhouse was built; rebuild it online.")
    if manifest.get("lock_sha256") != sha256(LOCK):
        raise RuntimeError("requirements.lock is missing or has changed.")
    wheels = manifest.get("wheels", {})
    if not wheels or set(wheels) != {path.name for path in WHEELHOUSE.glob("*.whl")}:
        raise RuntimeError("Wheelhouse files do not match the manifest.")
    for name, expected in wheels.items():
        if sha256(WHEELHOUSE / name) != expected:
            raise RuntimeError(f"Wheel checksum mismatch: {name}")
    for name, path in required_assets().items():
        if not path.is_file() or sha256(path) != manifest.get("assets", {}).get(name):
            raise RuntimeError(f"Missing or changed offline OCR asset: {path}")
    return manifest
