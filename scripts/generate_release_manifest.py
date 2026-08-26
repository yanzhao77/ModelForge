#!/usr/bin/env python3
"""Generate a credential-free release manifest without building artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "client" / "pyside6" / "version.py"


def _version() -> str:
    for line in VERSION_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("APP_VERSION = "):
            return line.split('"')[1]
    raise RuntimeError("APP_VERSION was not found")


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", required=True, choices=("macos-arm64", "windows-x64", "linux-x86_64"))
    parser.add_argument("--artifact", type=Path, help="Optional completed artifact to include with SHA-256")
    parser.add_argument("--output", type=Path, default=ROOT / "release-artifacts" / "release-manifest.json")
    args = parser.parse_args()

    manifest: dict[str, object] = {
        "schema_version": 1,
        "product": "ModelForge",
        "version": _version(),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_tag": _git("describe", "--tags", "--exact-match") if _git("tag", "--points-at", "HEAD") else None,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "platform": args.platform,
        "artifact": None,
        "signing": {"status": "unsigned", "provider": None},
        "sbom": "sbom.cdx.json",
    }
    if args.artifact:
        artifact = args.artifact.resolve()
        manifest["artifact"] = {"name": artifact.name, "sha256": _sha256(artifact), "bytes": artifact.stat().st_size}

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
