"""Create an OCR virtual environment using only the copied wheelhouse."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from offline_common import LOCK, REQUIREMENTS, SERVICE_ROOT, WHEELHOUSE, verify_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true", help="Check wheels and assets without installing")
    args = parser.parse_args()
    manifest = verify_manifest()
    print(f"Verified {len(manifest['wheels'])} wheels and local OCR assets for {manifest['target']}")
    if args.verify_only:
        return
    venv = SERVICE_ROOT / ".venv"
    python = venv / "Scripts" / "python.exe"
    if not python.is_file():
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    subprocess.run([str(python), "-m", "pip", "install", "--no-index", "--only-binary=:all:",
                    "--find-links", str(WHEELHOUSE), "-r", str(REQUIREMENTS), "-r", str(LOCK)], check=True)
    subprocess.run([str(python), "-m", "pip", "check"], check=True)
    subprocess.run([str(python), "-c", "from ocr_service.service import OcrService; "
                    "service = OcrService(); print(f'OCR ready: {len(service.form_definition().fields)} fields')"],
                   cwd=SERVICE_ROOT.parent, check=True)
    print(f"Offline installation complete: {python}")


if __name__ == "__main__":
    main()
