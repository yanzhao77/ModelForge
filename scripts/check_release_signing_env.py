#!/usr/bin/env python3
"""Report required signing configuration names without exposing secret values."""
from __future__ import annotations

import argparse
import os
import sys

REQUIRED = {
    "windows": (
        "MF_WINDOWS_SIGNING_CERT_BASE64",
        "MF_WINDOWS_SIGNING_CERT_PASSWORD",
        "MF_WINDOWS_TIMESTAMP_URL",
    ),
    "linux": (
        "MF_LINUX_GPG_PRIVATE_KEY",
        "MF_LINUX_GPG_KEY_FINGERPRINT",
        "MF_LINUX_GPG_PASSPHRASE",
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform", choices=sorted(REQUIRED))
    args = parser.parse_args()
    missing = [name for name in REQUIRED[args.platform] if not os.getenv(name)]
    print(f"platform={args.platform}")
    print("configured=" + ",".join(name for name in REQUIRED[args.platform] if name not in missing))
    print("missing=" + ",".join(missing))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
