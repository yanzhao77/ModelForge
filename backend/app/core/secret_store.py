"""Secret storage (V1.8): OS keychain first, encrypted file as fallback.

Remote provider credentials already live in an encrypted column whose key is
stored owner-only next to the database. This module adds the preferred path —
the operating system keychain — while keeping the existing encrypted store as a
working fallback so no deployment loses functionality.

Nothing here ever returns a secret to an API caller: only ``describe()`` is
exposed, which reports which backend is active and whether a name is set.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Any

SERVICE_NAME = "ModelForge"


def keychain_available() -> bool:
    try:
        if importlib.util.find_spec("keyring") is None:
            return False
    except (ImportError, ValueError):
        return False
    try:
        import keyring

        backend = keyring.get_keyring()
    except Exception:
        return False
    # ``keyring.backends.fail.Keyring`` means no usable backend is installed.
    return type(backend).__module__ != "keyring.backends.fail"


class SecretStore:
    """Store named secrets with keychain preference and file fallback."""

    def __init__(self, *, fallback_dir: str | os.PathLike[str] | None = None):
        self.fallback_dir = str(fallback_dir or "./data")

    # -- backend selection --------------------------------------------------

    def backend(self) -> str:
        return "keychain" if keychain_available() else "encrypted-file"

    def describe(self) -> dict[str, Any]:
        backend = self.backend()
        return {
            "backend": backend,
            "keychain_available": backend == "keychain",
            "fallback": "encrypted-provider-column",
            "notes": (
                []
                if backend == "keychain"
                else ["install 'keyring' to store secrets in the OS keychain"]
            ),
        }

    # -- operations ---------------------------------------------------------

    def set(self, name: str, value: str, *, username: str = "default") -> bool:
        """Store a secret; returns False when only the file fallback exists."""
        if not keychain_available():
            return False
        import keyring

        keyring.set_password(SERVICE_NAME, f"{username}:{name}", value)
        return True

    def get(self, name: str, *, username: str = "default") -> str | None:
        if not keychain_available():
            return None
        import keyring

        return keyring.get_password(SERVICE_NAME, f"{username}:{name}")

    def delete(self, name: str, *, username: str = "default") -> bool:
        if not keychain_available():
            return False
        import keyring
        from keyring.errors import KeyringError

        try:
            keyring.delete_password(SERVICE_NAME, f"{username}:{name}")
        except KeyringError:
            return False
        return True

    def status(self, names: list[str], *, username: str = "default") -> list[dict]:
        """Report presence without ever returning a value."""
        return [
            {"name": name, "configured": self.get(name, username=username) is not None}
            for name in names
        ]


secret_store = SecretStore()


def get_secret_store() -> SecretStore:
    return secret_store


__all__ = ["SERVICE_NAME", "SecretStore", "get_secret_store", "keychain_available", "secret_store"]
