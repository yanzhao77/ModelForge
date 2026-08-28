"""Containment checks for files exposed to an Agent Run.

The helpers are intentionally independent of API routing.  Any filesystem tool
must resolve an authenticated user's workspace here before opening a path.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

from core.config import settings


class AgentFileAccessError(ValueError):
    """Raised when a requested file is outside the safe Agent workspace."""


_SENSITIVE_FILENAMES = {
    ".env",
    ".remote_provider_fernet.key",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "known_hosts",
    "authorized_keys",
}
_SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".kdbx"}


def workspace_root_for_user(user_id: int | None) -> Path:
    """Return the only root an authenticated Agent Run may read from."""
    if user_id is None or user_id < 1:
        raise AgentFileAccessError("FILESYSTEM_USER_CONTEXT_REQUIRED")
    root = Path(settings.agent_workspace_root).expanduser().resolve()
    workspace = root / f"user-{user_id}"
    workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(workspace, 0o700)
    except OSError:
        # Permission normalization is best effort on filesystems that do not
        # support POSIX modes; containment remains mandatory below.
        pass
    return workspace.resolve()


def _contains_symbolic_link(candidate: Path, root: Path) -> bool:
    """Reject symlinks rather than relying solely on their resolved target."""
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        # Containment is checked after resolution; this is not itself a symlink.
        return False
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return True
    return False


def _is_sensitive(path: Path) -> bool:
    lowered = path.name.lower()
    return lowered in _SENSITIVE_FILENAMES or path.suffix.lower() in _SENSITIVE_SUFFIXES


def _resolve_workspace_path(path_value: str, user_id: int | None, *, missing_code: str) -> tuple[Path, Path]:
    if not path_value or not path_value.strip():
        raise AgentFileAccessError("FILE_PATH_REQUIRED")
    root = workspace_root_for_user(user_id)
    supplied = Path(path_value).expanduser()
    candidate = supplied if supplied.is_absolute() else root / supplied
    if supplied.is_absolute() and not candidate.is_relative_to(root):
        raise AgentFileAccessError("RESOURCE_OUTSIDE_ALLOWED_ROOT")
    if _contains_symbolic_link(candidate, root):
        raise AgentFileAccessError("SYMLINK_ACCESS_DENIED")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise AgentFileAccessError(missing_code) from exc
    if not resolved.is_relative_to(root):
        raise AgentFileAccessError("RESOURCE_OUTSIDE_ALLOWED_ROOT")
    if _is_sensitive(resolved):
        raise AgentFileAccessError("SENSITIVE_RESOURCE_DENIED")
    return root, resolved


def resolve_readable_agent_file(filepath: str, user_id: int | None) -> Path:
    """Return a regular non-sensitive file inside one user's workspace.

    Relative paths are rooted in the caller's workspace. Absolute paths are
    accepted only when they are already under that same workspace, which keeps
    clients flexible without exposing host paths.
    """
    _root, resolved = _resolve_workspace_path(filepath, user_id, missing_code="FILE_NOT_FOUND")
    try:
        mode = resolved.stat().st_mode
    except OSError as exc:
        raise AgentFileAccessError("FILE_NOT_FOUND") from exc
    if not stat.S_ISREG(mode):
        raise AgentFileAccessError("NON_REGULAR_FILE_DENIED")
    return resolved


def resolve_agent_directory(directory: str, user_id: int | None) -> tuple[Path, Path]:
    """Return the caller workspace and a regular directory within it."""
    root, resolved = _resolve_workspace_path(directory, user_id, missing_code="DIRECTORY_NOT_FOUND")
    if not resolved.is_dir():
        raise AgentFileAccessError("DIRECTORY_NOT_FOUND")
    return root, resolved


def read_agent_file(filepath: str, user_id: int | None) -> str:
    """Read a contained UTF-8 file subject to the configured byte ceiling."""
    path = resolve_readable_agent_file(filepath, user_id)
    limit = max(1, int(settings.agent_file_read_max_bytes))
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    truncated = len(data) > limit
    text = data[:limit].decode("utf-8", errors="replace")
    return text + ("\n... (truncated)" if truncated else "")
