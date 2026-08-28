from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class PermissionLevel:
    """Tool permission levels (spec 10)."""

    READ = "READ"
    FILESYSTEM_READ = "FILESYSTEM_READ"
    WRITE = "WRITE"
    EXECUTE = "EXECUTE"
    NETWORK = "NETWORK"
    SYSTEM = "SYSTEM"
    ADMIN = "ADMIN"


@dataclass
class ToolResult:
    """Unified tool output (spec 9)."""

    success: bool
    output: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, output: Any, **metadata: Any) -> ToolResult:
        return cls(success=True, output=output, metadata=metadata)

    @classmethod
    def err(cls, error: str, **metadata: Any) -> ToolResult:
        return cls(success=False, error=error, metadata=metadata)

    def to_text(self) -> str:
        if self.success:
            return str(self.output) if self.output is not None else "(no output)"
        return f"Error: {self.error}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "metadata": self.metadata,
        }


class Tool(ABC):
    """Standard Tool protocol (spec 9).

    name / description / schema() / async execute(arguments, context) -> ToolResult.
    Every dangerous tool declares its permissions (spec 10); policy is enforced
    by the runtime before execution (spec 69).
    """

    name: str = ""
    description: str = ""
    version: str = "1.0.0"
    permissions: list[str] = []
    timeout: float = 60.0
    retry_count: int = 0
    retry_delay: float = 1.0
    retryable_errors: list[str] = []
    source: str = "builtin"
    metadata: dict[str, Any] = {}
    aliases: list[str] = []

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def schema(self) -> dict[str, Any]:
        """OpenAI-compatible tool schema (spec 9: def schema())."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema(),
            },
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "permissions": list(self.permissions),
            "timeout": self.timeout,
            "retry_policy": {
                "retry_count": self.retry_count,
                "retry_delay": self.retry_delay,
                "retryable_errors": list(self.retryable_errors),
            },
            "source": self.source,
            "input_schema": self.input_schema(),
            "aliases": list(self.aliases),
            "metadata": self.metadata,
        }

    @abstractmethod
    async def execute(
        self,
        arguments: dict[str, Any],
        context: Any,
    ) -> ToolResult:
        """Execute the tool with validated arguments (spec 9)."""
        ...