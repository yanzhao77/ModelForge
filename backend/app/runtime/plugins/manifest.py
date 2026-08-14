from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

import yaml


PLUGIN_TYPES = ("tool", "agent", "skill")


@dataclass
class PluginManifest:
    """Plugin metadata (audit §16 / §17: filesystem-first).

    `tools` is a list of tool descriptors `{name, description, input_schema}`;
    actual execution comes from the `entry` module (importable file exposing
    `get_tools(ctx)` and/or `setup(ctx)`), so code stays in files, not DB.
    """

    name: str
    version: str = "1.0.0"
    type: str = "tool"
    description: str = ""
    entry: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    tools: List[Dict[str, Any]] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> List[str]:
        problems = []
        if not self.name:
            problems.append("name is required")
        if self.type not in PLUGIN_TYPES:
            problems.append(f"type must be one of {PLUGIN_TYPES}")
        if self.type == "tool" and not self.entry and not self.tools:
            problems.append("tool plugin needs entry or tools")
        return problems

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PluginManifest":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_file(cls, path: str) -> "PluginManifest":
        with open(path, "r", encoding="utf-8") as f:
            if path.endswith(".json"):
                data = json.load(f)
            else:
                data = yaml.safe_load(f) or {}
        manifest = cls.from_dict(data)
        # resolve entry relative to the manifest directory (filesystem-first)
        if manifest.entry and not os.path.isabs(manifest.entry):
            manifest.entry = os.path.join(os.path.dirname(path), manifest.entry)
        return manifest