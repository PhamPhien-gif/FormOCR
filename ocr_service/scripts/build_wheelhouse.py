"""Download a complete binary wheelhouse for this Windows/Python environment."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

from offline_common import (LOCK, MANIFEST, REQUIREMENTS, WHEELHOUSE,
                            required_assets, sha256, target_info, verify_manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="Replace a previously built wheelhouse")
    args = parser.parse_args()
    target = target_info()
    if target["platform"] != "win-amd64" or target["implementation"] != "CPython":
        raise SystemExit(f"This bundle is intended for 64-bit Windows CPython; current target is {target}")
    missing = [str(path) for path in required_assets().values() if not path.is_file()]
    if missing:
        raise SystemExit("Download/copy the local OCR models and reference PDF first: " + ", ".join(missing))
    WHEELHOUSE.mkdir(parents=True, exist_ok=True)
    if WHEELHOUSE.is_symlink() or not WHEELHOUSE.resolve().is_relative_to(REQUIREMENTS.parent.resolve()):
        raise SystemExit("Unexpected wheelhouse path")
    if MANIFEST.exists() and not args.refresh:
        try:
            existing = verify_manifest()
        except (RuntimeError, OSError, ValueError) as exc:
            raise SystemExit(f"Existing wheelhouse is incomplete: {exc}. Rebuild with --refresh.") from exc
        print(f"Wheelhouse already verified: {len(existing['wheels'])} wheels in {WHEELHOUSE}")
        return
    if args.refresh:
        for path in WHEELHOUSE.glob("*.whl"):
            path.unlink()
        MANIFEST.unlink(missing_ok=True)
        LOCK.unlink(missing_ok=True)
    elif any(WHEELHOUSE.iterdir()):
        raise SystemExit("Wheelhouse contains files without a valid manifest; rerun with --refresh.")

    subprocess.run([sys.executable, "-m", "pip", "download", "--only-binary=:all:",
                    "--dest", str(WHEELHOUSE), "-r", str(REQUIREMENTS)], check=True)
    wheels = sorted(WHEELHOUSE.glob("*.whl"))
    if not wheels:
        raise SystemExit("pip did not download any wheels")
    locked = {}
    for path in wheels:
        name, version, *_ = path.name.split("-")
        if name in locked and locked[name] != version:
            raise SystemExit(f"Multiple versions of {name} found in wheelhouse")
        locked[name] = version
    LOCK.write_text("# Resolved by build_wheelhouse.py for this Python target.\n" +
                    "".join(f"{name}=={version}\n" for name, version in sorted(locked.items())),
                    encoding="utf-8")
    subprocess.run([sys.executable, "-m", "pip", "install", "--dry-run", "--ignore-installed",
                    "--no-index", "--only-binary=:all:", "--find-links", str(WHEELHOUSE),
                    "-r", str(REQUIREMENTS), "-r", str(LOCK)], check=True)
    manifest = {
        "format_version": 1,
        "target": target,
        "requirements_sha256": sha256(REQUIREMENTS),
        "lock_sha256": sha256(LOCK),
        "wheels": {path.name: sha256(path) for path in wheels},
        "assets": {name: sha256(path) for name, path in required_assets().items()},
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    verify_manifest()
    print(f"Ready: {len(wheels)} wheels ({sum(path.stat().st_size for path in wheels) / 1024**2:.1f} MiB) for {target}")
    print(f"Copy the entire ocr_service directory, including wheelhouse and models, to the target machine.")


if __name__ == "__main__":
    main()
