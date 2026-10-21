"""Download the official Qwen3-VL-2B Q4_K_M GGUF and its vision projector."""
from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import hf_hub_download


REPO_ID = "Qwen/Qwen3-VL-2B-Instruct-GGUF"
MODEL_FILE = "Qwen3VL-2B-Instruct-Q4_K_M.gguf"
PROJECTOR_FILE = "mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf"
DEFAULT_DIR = Path("models/Qwen3-VL-2B-Q4_K_M")


def verify_model(directory: Path) -> None:
    for name, minimum_size in ((MODEL_FILE, 900_000_000), (PROJECTOR_FILE, 350_000_000)):
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
    print(f"Offline GGUF model ready: {destination}")


if __name__ == "__main__":
    main()
