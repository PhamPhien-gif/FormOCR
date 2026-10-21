"""Download the official PaddleOCR-VL-1.6 GGUF model and vision projector."""
from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import hf_hub_download


REPO_ID = "PaddlePaddle/PaddleOCR-VL-1.6-GGUF"
MODEL_FILE = "PaddleOCR-VL-1.6-GGUF.gguf"
PROJECTOR_FILE = "PaddleOCR-VL-1.6-GGUF-mmproj.gguf"
DEFAULT_DIR = Path("models/PaddleOCR-VL-1.6-GGUF")


def verify_model(directory: Path) -> None:
    for name, minimum_size in ((MODEL_FILE, 900_000_000), (PROJECTOR_FILE, 850_000_000)):
        path = directory / name
        if not path.is_file() or path.stat().st_size < minimum_size:
            raise RuntimeError(f"Missing or incomplete GGUF file: {path}")
        with path.open("rb") as handle:
            if handle.read(4) != b"GGUF":
                raise RuntimeError(f"Invalid GGUF header: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_DIR)
    args = parser.parse_args()
    destination = args.output.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    for name in (MODEL_FILE, PROJECTOR_FILE):
        print(f"Preparing {name}...", flush=True)
        hf_hub_download(REPO_ID, filename=name, local_dir=destination)
    verify_model(destination)
    print(f"Offline PaddleOCR-VL model ready: {destination}")


if __name__ == "__main__":
    main()
