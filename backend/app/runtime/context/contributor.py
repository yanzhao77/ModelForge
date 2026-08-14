from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol, runtime_checkable


@dataclass
class ContextSegment:
    """A prioritized context contribution (audit §9.3 / §16.3).

    section: system | memory | knowledge | skill | instruction
    priority: lower = injected earlier (0..100)
    """

    content: str
    section: str = "system"
    priority: int = 50

    def to_dict(self) -> Dict[str, Any]:
        return {"content": self.content, "section": self.section, "priority": self.priority}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContextSegment":
        return cls(
            content=data.get("content", ""),
            section=data.get("section", "system"),
            priority=int(data.get("priority", 50)),
        )


@runtime_checkable
class ContextContributor(Protocol):
    """A plugin/extension can contribute prompt segments without modifying
    ContextBuilder core (audit §9.3).
    """

    name: str

    def contribute(self, ctx: Any) -> List[ContextSegment]:
        """Return segments to inject into the system context."""
        ...