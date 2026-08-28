"""Pure desktop presentation model for read-only execution-intent previews."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from i18n.ui_localizer import format_text


@dataclass(frozen=True)
class ExecutionIntentPreviewView:
    """Safe fields a desktop view may present without retaining a preview token."""

    action: str
    object_type: str
    risk_tier: str
    target_count: int
    expires_at: str
    version_binding_complete: bool
    execution_blocked: bool

    @classmethod
    def from_response(cls, payload: dict[str, Any]) -> "ExecutionIntentPreviewView":
        """Project only content-free summary fields from a preview response."""
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        return cls(
            action=str(summary.get("action") or ""),
            object_type=str(summary.get("object_type") or ""),
            risk_tier=str(summary.get("risk_tier") or ""),
            target_count=max(0, int(summary.get("target_count") or 0)),
            expires_at=str(payload.get("expires_at") or ""),
            version_binding_complete=bool(summary.get("target_version_binding_complete")),
            execution_blocked=bool(payload.get("execution_blocked", True)),
        )

    @property
    def can_execute(self) -> bool:
        """Previews must never grant desktop execution authority."""
        return False

    def localized_lines(self) -> tuple[str, str, str]:
        """Return presentation-only text without exposing tokens, IDs, or digests."""
        binding_state = format_text("完整") if self.version_binding_complete else format_text("未完整")
        return (
            format_text("执行意图预览（只读）"),
            format_text(
                "预览动作：{action}｜对象：{object_type}｜风险：{risk_tier}｜目标：{target_count}",
                action=self.action,
                object_type=self.object_type,
                risk_tier=self.risk_tier,
                target_count=self.target_count,
            ),
            format_text("预览已阻断执行，确认不会启动任何操作。")
            + " "
            + format_text("版本绑定状态：{state}", state=binding_state),
        )
