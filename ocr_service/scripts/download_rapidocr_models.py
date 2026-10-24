"""Download the RapidOCR PP-OCRv5 mobile detector and English recognizer for offline use."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import requests


BASE = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv5"
FILES = {
    "ch_PP-OCRv5_det_mobile.onnx": (f"{BASE}/det/ch_PP-OCRv5_det_mobile.onnx", "4d97c44a20d30a81aad087d6a396b08f786c4635742afc391f6621f5c6ae78ae"),
    "en_PP-OCRv5_rec_mobile.onnx": (f"{BASE}/rec/en_PP-OCRv5_rec_mobile.onnx", "c3461add59bb4323ecba96a492ab75e06dda42467c9e3d0c18db5d1d21924be8"),
}
DEFAULT_DIR = Path(__file__).resolve().parents[1] / "models" / "rapidocr-ppocrv5-en"


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_DIR)
    destination = parser.parse_args().output.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    for name, (url, expected) in FILES.items():
        path = destination / name
        if path.is_file() and digest(path) == expected:
            print(f"Verified {path}", flush=True)
            continue
        temporary = path.with_suffix(path.suffix + ".part")
        print(f"Downloading {name}...", flush=True)
        with requests.get(url, stream=True, timeout=120) as response:
            response.raise_for_status()
            with temporary.open("wb") as output:
                for chunk in response.iter_content(1024 * 1024):
                    output.write(chunk)
        if digest(temporary) != expected:
            raise RuntimeError(f"Checksum mismatch for {name}")
        temporary.replace(path)
    print(f"Offline RapidOCR models ready: {destination}")


if __name__ == "__main__":
    main()
