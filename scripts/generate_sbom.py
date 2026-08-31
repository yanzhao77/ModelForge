#!/usr/bin/env python3
"""Generate a lightweight CycloneDX dependency inventory without installing packages."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _components(requirements: Path) -> list[dict[str, str]]:
    components: list[dict[str, str]] = []
    for raw in requirements.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(("-", "git+", "http:")):
            continue
        name, separator, version = line.partition("==")
        components.append({"type": "library", "name": name.strip(), "version": version.strip() if separator else "unbounded"})
    return components


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirements", type=Path, default=ROOT / "requirements.txt")
    parser.add_argument("--output", type=Path, default=ROOT / "release-artifacts" / "sbom.cdx.json")
    args = parser.parse_args()
    source = args.requirements.resolve()
    output = args.output.resolve()
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": "urn:uuid:pending-release-build",
        "version": 1,
        "metadata": {"timestamp": datetime.now(UTC).isoformat(), "component": {"type": "application", "name": "ModelForge"}},
        "components": _components(source),
        "properties": [{"name": "org.modelforge.sbom.source", "value": str(source.relative_to(ROOT))}],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(bom, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
