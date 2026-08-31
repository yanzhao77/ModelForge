#!/usr/bin/env python3
"""Validate only the structure of a redacted v0.1.3 release-decision manifest.

This script never runs tests, builds, signing tools, installers, model calls,
network operations, Git tag creation, or release publishing.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REQUIRED_GATES = (
    "i1_migration",
    "i2_concurrency_events",
    "i3_control_plane_audit",
    "i4_lifecycle",
    "i5_desktop",
    "windows_signing_install",
    "linux_signing_install",
    "release_approval",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a redacted ModelForge release-decision manifest")
    parser.add_argument("manifest", type=Path, help="Path to a JSON decision manifest")
    parser.add_argument("--commit", required=True, help="Expected full candidate commit SHA")
    parser.add_argument("--version", required=True, help="Expected non-development application version")
    args = parser.parse_args()

    try:
        data = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"decision manifest unavailable: {exc}")
        return 2

    errors: list[str] = []
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        errors.append("expected commit must be a full lowercase 40-character SHA")
    if args.version.endswith("-dev"):
        errors.append("release decision cannot target a development version")
    if data.get("commit") != args.commit:
        errors.append("manifest commit does not match the fixed candidate SHA")
    if data.get("version") != args.version:
        errors.append("manifest version does not match the requested release version")
    if data.get("candidate_type") != "release-candidate":
        errors.append("manifest candidate_type must be release-candidate")

    gates = data.get("gates") if isinstance(data.get("gates"), dict) else {}
    for gate in REQUIRED_GATES:
        record = gates.get(gate)
        if not isinstance(record, dict) or record.get("status") != "passed":
            errors.append(f"required gate missing or not passed: {gate}")
        elif not record.get("evidence_ref"):
            errors.append(f"required gate has no redacted evidence_ref: {gate}")

    if errors:
        print("release decision is incomplete:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("release decision manifest contains all required gate records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
