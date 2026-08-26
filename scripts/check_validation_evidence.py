#!/usr/bin/env python3
"""Check the shape of a release-validation evidence manifest.

This script never runs tests, builds, signing tools, installers, models, or
network calls. It only checks that a future human-produced, redacted manifest
is tied to the intended commit and records the mandatory gate outcomes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED_GATES = (
    "b2_migration",
    "c3_concurrency",
    "d4_sse_outbox",
    "e5_lifecycle",
    "f6_plugin_governance",
    "g7_desktop",
    "windows_signing_install",
    "linux_signing_install",
    "release_approval",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a redacted ModelForge release-evidence manifest")
    parser.add_argument("evidence", type=Path, help="Path to a JSON evidence manifest")
    parser.add_argument("--commit", required=True, help="Expected full candidate commit SHA")
    parser.add_argument("--version", required=True, help="Expected application version, for example 0.1.2")
    args = parser.parse_args()

    try:
        data = json.loads(args.evidence.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"evidence manifest unavailable: {exc}")
        return 2

    errors: list[str] = []
    if data.get("commit") != args.commit:
        errors.append("commit does not match the fixed candidate SHA")
    if data.get("version") != args.version:
        errors.append("version does not match the requested release version")
    gates = data.get("gates") if isinstance(data.get("gates"), dict) else {}
    for gate in REQUIRED_GATES:
        record = gates.get(gate)
        if not isinstance(record, dict) or record.get("status") != "passed":
            errors.append(f"required gate missing or not passed: {gate}")
            continue
        if not record.get("evidence_ref"):
            errors.append(f"required gate has no redacted evidence_ref: {gate}")

    if errors:
        print("release evidence is incomplete:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("release evidence manifest contains all required gate records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
