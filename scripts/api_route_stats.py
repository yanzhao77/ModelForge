#!/usr/bin/env python3
"""Report the API route/operation counts from the live OpenAPI schema.

MF-REL-001: the README's API badge and overview section previously stated a
hand-written route count that drifted from the real application. This script
derives the authoritative counts from ``app.openapi()`` and, with ``--check``,
verifies the README states the same numbers so documentation cannot silently
rot. It performs no network calls and creates no files.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "backend" / "app"
README = ROOT / "README.md"

_METHODS = ("get", "post", "put", "patch", "delete", "options", "head", "trace")


def _openapi_spec() -> dict:
    sys.path.insert(0, str(APP_DIR))
    from main import app  # noqa: PLC0415

    return app.openapi()


def _counts(spec: dict) -> tuple[int, int]:
    paths = spec.get("paths", {})
    operations = 0
    for path in paths.values():
        operations += sum(1 for method in _METHODS if method in path)
    return len(paths), operations


def _readme_numbers() -> tuple[int, int]:
    full = README.read_text(encoding="utf-8")
    badge = re.search(r"API-(\d+)\s*paths/(\d+)\s*ops-", full)
    overview = re.search(r"API 概览（(\d+)\s*paths\s*/\s*(\d+)\s*operations", full)
    if badge:
        return int(badge.group(1)), int(badge.group(2))
    if overview:
        return int(overview.group(1)), int(overview.group(2))
    raise RuntimeError("README does not contain a recognized route-count marker")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify the README matches the live counts")
    args = parser.parse_args()

    if not os.environ.get("DATABASE_PATH"):
        os.environ["DATABASE_PATH"] = str(ROOT / "data" / "modelforge.db")

    paths, operations = _counts(_openapi_spec())
    print(f"paths={paths} operations={operations}")

    if args.check:
        stated_paths, stated_ops = _readme_numbers()
        errors: list[str] = []
        if stated_paths != paths:
            errors.append(f"README path count {stated_paths} != live {paths}")
        if stated_ops != operations:
            errors.append(f"README operation count {stated_ops} != live {operations}")
        if errors:
            print("README route stats are stale:")
            for error in errors:
                print(f"- {error}")
            return 1
        print("README route stats are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
