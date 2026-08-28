from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..tools.base import PermissionLevel


@dataclass
class PolicyDecision:
    """Result of a tool policy check."""

    allowed: bool
    reason: str = ""
    require_approval: bool = False

    @classmethod
    def allow(cls, reason: str = "allowed") -> PolicyDecision:
        return cls(True, reason)

    @classmethod
    def deny(cls, reason: str) -> PolicyDecision:
        return cls(False, reason)

    @classmethod
    def approval(cls, reason: str = "requires human approval") -> PolicyDecision:
        return cls(True, reason, require_approval=True)


@dataclass
class Policy:
    """Runtime policy (spec 33). Dangerous capabilities are OFF by default (spec 34)."""

    allowed_tools: list[str] | None = None
    denied_tools: list[str] = field(default_factory=list)
    allowed_models: list[str] | None = None
    network_access: bool = False
    shell_access: bool = False
    filesystem_access: bool = False
    filesystem_write: bool = False
    max_iterations: int | None = None
    max_tool_calls: int | None = None
    human_approval_required: bool = False
    require_approval_for: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def check_tool(
        self,
        ctx: Any,
        tool_name: str,
        tool: Any = None,
    ) -> PolicyDecision:
        """Decide whether a tool call is allowed (spec 69: 检查在 Tool 执行前)."""
        if tool_name in self.denied_tools:
            return PolicyDecision.deny(f"tool {tool_name} is denied by policy")
        if self.allowed_tools is not None and tool_name not in self.allowed_tools:
            return PolicyDecision.deny(f"tool {tool_name} not in allowed_tools")

        perms = list(getattr(tool, "permissions", []) or []) if tool is not None else []
        if PermissionLevel.NETWORK in perms and not self.network_access:
            return PolicyDecision.deny("network access is not allowed by policy")
        if PermissionLevel.EXECUTE in perms and not self.shell_access:
            return PolicyDecision.deny("shell/execute is not allowed by policy")
        if PermissionLevel.FILESYSTEM_READ in perms and not self.filesystem_access:
            return PolicyDecision.deny("filesystem read is not allowed by policy")
        if PermissionLevel.WRITE in perms and not self.filesystem_write:
            return PolicyDecision.deny("filesystem write is not allowed by policy")

        if self.human_approval_required or tool_name in self.require_approval_for:
            return PolicyDecision.approval()
        return PolicyDecision.allow()

    @classmethod
    def from_settings(cls, settings: Any) -> Policy:
        p = settings.policy
        return cls(
            network_access=bool(p.default_network_access),
            shell_access=bool(p.default_shell_access),
            filesystem_access=bool(p.default_filesystem_access),
        )


class PolicyEngine:
    """Resolves per-agent policies merged over runtime defaults (spec 33)."""

    def __init__(self, defaults: Policy | None = None, settings: Any = None):
        self.defaults = defaults or Policy.from_settings(settings)

    def for_agent(self, agent: Any) -> Policy:
        raw = agent.policy if agent is not None else None
        if not raw:
            return self.defaults
        data = asdict(self.defaults)
        data.update({k: v for k, v in raw.items() if k in data})
        return Policy(**data)

    def default(self) -> Policy:
        return self.defaults