"""Tool Registry (spec 8). Phase 2 ships the legacy bridge; Phase 4 adds the full registry."""

from .legacy import LegacyToolRunner, LEGACY_TOOL_SCHEMAS

__all__ = ["LegacyToolRunner", "LEGACY_TOOL_SCHEMAS"]