"""Pack the OCR service, wheels and models into one portable ZIP file."""
from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from offline_common import SERVICE_ROOT, verify_manifest


EXCLUDED_DIRS = {".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".part", ".log"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="ZIP destination (defaults beside ocr_service)")
    args = parser.parse_args()
    target = verify_manifest()["target"]
    output = args.output or SERVICE_ROOT.parent / f"ocr_service-{target['platform']}-py{target['python'].replace('.', '')}.zip"
    output = output.resolve()
    if output.is_relative_to(SERVICE_ROOT):
        raise SystemExit("Place the ZIP outside ocr_service to avoid including it in itself.")
    if output.exists():
        raise SystemExit(f"Archive already exists: {output}. Remove or choose another --output path.")
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(SERVICE_ROOT.rglob("*")):
            relative = path.relative_to(SERVICE_ROOT)
            if any(part in EXCLUDED_DIRS for part in relative.parts) or path.suffix in EXCLUDED_SUFFIXES:
                continue
            if path.is_symlink():
                raise SystemExit(f"Cannot pack a symbolic link: {path}")
            if path.is_file():
                archive.write(path, Path("ocr_service") / relative)
                count += 1
    print(f"Created {output} with {count} files ({output.stat().st_size / 1024**2:.1f} MiB)")
    print("On the target machine: extract the ZIP, then run python ocr_service\\scripts\\install_offline.py")


if __name__ == "__main__":
    main()
