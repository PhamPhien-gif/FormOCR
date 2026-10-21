"""Install an official Windows CPU llama.cpp release inside this project."""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import requests


DEFAULT_DIR = Path("runtime/llama.cpp")
RELEASES_URL = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=10"


def choose_asset(releases: list[dict]) -> tuple[str, str]:
    for release in releases:
        for asset in release.get("assets", []):
            if asset["name"].endswith("-bin-win-cpu-x64.zip"):
                return release["tag_name"], asset["browser_download_url"]
    raise RuntimeError("No Windows x64 CPU llama.cpp asset found in recent releases")


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("This installer is for Windows x64; install llama.cpp for your platform manually")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_DIR)
    args = parser.parse_args()
    destination = args.output.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    response = requests.get(RELEASES_URL, timeout=30)
    response.raise_for_status()
    tag, url = choose_asset(response.json())
    print(f"Downloading official llama.cpp {tag} Windows CPU build...", flush=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        archive = Path(temporary) / "llama.zip"
        with requests.get(url, stream=True, timeout=120) as download:
            download.raise_for_status()
            with archive.open("wb") as output:
                shutil.copyfileobj(download.raw, output)
        with zipfile.ZipFile(archive) as zipped:
            for member in zipped.infolist():
                target = (destination / member.filename).resolve()
                if not target.is_relative_to(destination):
                    raise RuntimeError(f"Unsafe archive path: {member.filename}")
            zipped.extractall(destination)
    binaries = list(destination.rglob("llama-server.exe"))
    if len(binaries) != 1:
        raise RuntimeError("Downloaded archive does not contain exactly one llama-server.exe")
    print(f"llama.cpp {tag} ready: {binaries[0]}")


if __name__ == "__main__":
    main()
