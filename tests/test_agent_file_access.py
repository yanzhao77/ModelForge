"""Security regression tests for Agent filesystem tool containment."""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from core.agent_file_access import (
    AgentFileAccessError,
    resolve_readable_agent_file,
    workspace_root_for_user,
)
from core.config import settings
from runtime.policy import Policy
from runtime.tools.builtin import register_builtin_tools
from runtime.tools.registry import ToolRegistry
from services.agent_tools import tool_file_read


@pytest.fixture()
def workspace_root(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "agent_workspace_root", str(tmp_path / "agent-workspaces"))
    monkeypatch.setattr(settings, "agent_file_read_max_bytes", 64)
    return tmp_path


def test_filesystem_policy_is_disabled_by_default():
    registry = register_builtin_tools(ToolRegistry())
    decision = Policy().check_tool(None, "filesystem.read", registry.get("filesystem.read"))
    assert decision.allowed is False


def test_file_tool_reads_only_owner_workspace(workspace_root):
    workspace = workspace_root_for_user(7)
    (workspace / "notes.txt").write_text("safe content", encoding="utf-8")

    assert tool_file_read("notes.txt", SimpleNamespace(user_id=7)) == "safe content"
    with pytest.raises(AgentFileAccessError, match="RESOURCE_OUTSIDE_ALLOWED_ROOT"):
        resolve_readable_agent_file(str(workspace_root / "outside.txt"), 7)


def test_file_tool_rejects_sensitive_and_symlink_resources(workspace_root):
    workspace = workspace_root_for_user(8)
    (workspace / ".env").write_text("API_KEY=secret", encoding="utf-8")
    (workspace / "normal.txt").write_text("normal", encoding="utf-8")
    (workspace / "linked.txt").symlink_to(workspace / "normal.txt")

    with pytest.raises(AgentFileAccessError, match="SENSITIVE_RESOURCE_DENIED"):
        resolve_readable_agent_file(".env", 8)
    with pytest.raises(AgentFileAccessError, match="SYMLINK_ACCESS_DENIED"):
        resolve_readable_agent_file("linked.txt", 8)


def test_file_tool_requires_authenticated_run_owner(workspace_root):
    with pytest.raises(AgentFileAccessError, match="FILESYSTEM_USER_CONTEXT_REQUIRED"):
        tool_file_read("anything.txt", SimpleNamespace(user_id=None))
