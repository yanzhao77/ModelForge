from __future__ import annotations

from typing import Any


class RuntimeError(Exception):
    """Base error for the Agent Runtime (spec Phase 1: RuntimeError)."""

    code: str = "RUNTIME_ERROR"
    http_status: int = 500
    default_message: str = "Runtime error"

    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None):
        self.message = message or self.default_message
        self.details: dict[str, Any] = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


class AgentNotFoundError(RuntimeError):
    code = "AGENT_NOT_FOUND"
    http_status = 404
    default_message = "Agent not found"


class RunNotFoundError(RuntimeError):
    code = "RUN_NOT_FOUND"
    http_status = 404
    default_message = "Run not found"


class RunCancelledError(RuntimeError):
    code = "RUN_CANCELLED"
    http_status = 409
    default_message = "Run cancelled"


class RunTimeoutError(RuntimeError):
    code = "RUN_TIMEOUT"
    http_status = 408
    default_message = "Run timed out"


class ToolNotFoundError(RuntimeError):
    code = "TOOL_NOT_FOUND"
    http_status = 404
    default_message = "Tool not found"


class ToolDeniedError(RuntimeError):
    code = "TOOL_DENIED"
    http_status = 403
    default_message = "Tool call denied by policy"


class ToolTimeoutError(RuntimeError):
    code = "TOOL_TIMEOUT"
    http_status = 408
    default_message = "Tool execution timed out"


class ModelNotFoundError(RuntimeError):
    code = "MODEL_NOT_FOUND"
    http_status = 404
    default_message = "Model not found"


class ModelUnavailableError(RuntimeError):
    code = "MODEL_UNAVAILABLE"
    http_status = 503
    default_message = "Model unavailable"


class ContextTooLargeError(RuntimeError):
    code = "CONTEXT_TOO_LARGE"
    http_status = 413
    default_message = "Context budget exceeded"


class PolicyDeniedError(RuntimeError):
    code = "POLICY_DENIED"
    http_status = 403
    default_message = "Action denied by policy"


class HumanApprovalRequiredError(RuntimeError):
    code = "HUMAN_APPROVAL_REQUIRED"
    http_status = 402
    default_message = "Human approval required"


class AgentLoopLimitError(RuntimeError):
    code = "AGENT_LOOP_LIMIT"
    http_status = 422
    default_message = "Agent loop limit exceeded"


class AgentToolCallLimitError(RuntimeError):
    code = "AGENT_TOOL_CALL_LIMIT"
    http_status = 422
    default_message = "Tool call limit exceeded"


#: All defined error codes (spec 47 list + loop limits)
ERROR_CODES = (
    "AGENT_NOT_FOUND", "RUN_NOT_FOUND", "RUN_CANCELLED", "RUN_TIMEOUT",
    "TOOL_NOT_FOUND", "TOOL_DENIED", "TOOL_TIMEOUT", "MODEL_NOT_FOUND",
    "MODEL_UNAVAILABLE", "CONTEXT_TOO_LARGE", "POLICY_DENIED",
    "HUMAN_APPROVAL_REQUIRED", "RUNTIME_ERROR", "AGENT_LOOP_LIMIT",
    "AGENT_TOOL_CALL_LIMIT",
)