#!/usr/bin/env python3
"""Generate a CycloneDX SBOM from the full installed dependency tree.

Two modes:
  --mode=requirements   Parse a requirements.txt file (fast, no install needed).
                        **WARNING**: Only lists direct dependencies; transitive
                        deps are excluded. Use for lightweight inventory only.
  --mode=installed      Query importlib.metadata for the complete installed
                        dependency tree including all transitive packages.
                        This is the recommended mode for release SBOMs.

Default is ``--mode=installed``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from importlib.metadata import distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _components_from_installed() -> list[dict[str, str]]:
    """Return all installed packages with their versions and suppliers."""
    components: list[dict[str, str]] = []
    seen: set[str] = set()
    for dist in distributions():
        name = dist.metadata["Name"]
        if name in seen:
            continue
        seen.add(name)
        version = dist.metadata["Version"] or "unknown"
        summary = dist.metadata.get("Summary", "") or ""
        home = dist.metadata.get("Home-page", "") or ""
        components.append({
            "type": "library",
            "name": name,
            "version": version,
            "description": summary[:200] if summary else "",
            "purl": f"pkg:pypi/{name.lower()}@{version}",
            **(({"externalReferences": [{"url": home, "type": "website"}]} if home and home != "UNKNOWN" else {})),
        })
    components.sort(key=lambda c: c["name"].lower())
    return components


def _components_from_requirements(requirements: Path) -> list[dict[str, str]]:
    """Parse a requirements.txt file. Only lists direct deps (no transitive)."""
    components: list[dict[str, str]] = []
    for raw in requirements.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(("-", "git+", "http:")):
            continue
        name, separator, version = line.partition("==")
        components.append({
            "type": "library",
            "name": name.strip(),
            "version": version.strip() if separator else "unbounded",
        })
    return components


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=["installed", "requirements"], default="installed",
        help="SBOM source: 'installed' (full tree) or 'requirements' (direct only)",
    )
    parser.add_argument("--requirements", type=Path, default=ROOT / "requirements.txt")
    parser.add_argument("--output", type=Path, default=ROOT / "release-artifacts" / "sbom.cdx.json")
    parser.add_argument(
        "--source-label",
        type=str,
        default=None,
        help="Explicit source label to record in SBOM metadata. "
        "REQUIRED when claiming a runtime or image source; otherwise the SBOM "
        "will be marked as 'unspecified-installed' which is NOT authoritative "
        "for production runtime claim.",
    )
    args = parser.parse_args()

    if args.mode == "installed":
        components = _components_from_installed()
        if args.source_label:
            source_label = args.source_label
        else:
            source_label = f"unspecified-installed ({len(components)} packages)"
            print(
                "WARNING: --source-label not provided. SBOM source is recorded as "
                "'unspecified-installed' which does not claim a runtime or image "
                "source. For authoritative runtime SBOM, pass "
                "'--source-label=isolated-runtime-venv' or "
                "'--source-label=docker-image:<tag>'.",
                file=sys.stderr,
            )
    else:
        components = _components_from_requirements(args.requirements)
        source_label = args.source_label or str(args.requirements.relative_to(ROOT))
        print(
            "WARNING: --mode=requirements only lists direct dependencies. "
            "Transitive packages are NOT included. Use --mode=installed for "
            "a complete SBOM.",
            file=sys.stderr,
        )

    output = args.output.resolve()
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": "urn:uuid:pending-release-build",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "component": {"type": "application", "name": "ModelForge"},
            "tools": [{"name": "generate_sbom.py", "version": "2.0"}],
        },
        "components": components,
        "properties": [
            {"name": "org.modelforge.sbom.source", "value": source_label},
            {"name": "org.modelforge.sbom.python", "value": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"},
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(bom, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"SBOM written to {output} ({len(components)} components)")


if __name__ == "__main__":
    main()
