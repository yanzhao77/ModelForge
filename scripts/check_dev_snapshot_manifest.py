#!/usr/bin/env python3
"""Validate a future development snapshot manifest without Git or network actions."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SHA40 = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_STATUS = "not_validated"


def fail(message: str) -> int:
    print(f"INVALID: {message}")
    return 2


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        return fail("usage: check_dev_snapshot_manifest.py <manifest.json>")
    try:
        payload = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return fail(f"cannot read JSON manifest: {exc}")
    if payload.get("schema_version") != "1.0":
        return fail("schema_version must be 1.0")
    snapshot = payload.get("snapshot")
    validation = payload.get("validation")
    security = payload.get("security")
    if not isinstance(snapshot, dict) or not isinstance(validation, dict) or not isinstance(security, dict):
        return fail("snapshot, validation, and security objects are required")
    if not isinstance(snapshot.get("name"), str) or not snapshot["name"].startswith("v0.1.3-dev."):
        return fail("snapshot.name must use a new v0.1.3-dev.N name")
    if not isinstance(snapshot.get("commit_sha"), str) or not SHA40.fullmatch(snapshot["commit_sha"]):
        return fail("snapshot.commit_sha must be a lowercase 40-character SHA")
    if snapshot.get("tag_type") != "annotated":
        return fail("snapshot.tag_type must be annotated")
    base_tag = snapshot.get("base_tag")
    if not isinstance(base_tag, dict) or base_tag.get("name") != "v0.1.3-dev" or base_tag.get("immutable") is not True:
        return fail("base_tag must retain immutable v0.1.3-dev")
    includes = snapshot.get("includes")
    if not isinstance(includes, list) or not includes or not all(isinstance(item, str) and item.strip() for item in includes):
        return fail("snapshot.includes must contain at least one work-package identifier")
    if validation.get("status") != REQUIRED_STATUS:
        return fail("development manifests must remain not_validated before separately authorized verification")
    if security.get("contains_secrets") is not False or security.get("contains_unredacted_payloads") is not False:
        return fail("manifest must declare no secrets or unredacted payloads")
    print("VALID: development snapshot manifest structure only; no Git, network, or validation action was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
