"""Plugin infrastructure (3.x Composable Agent & Tool Plugin, audit §16).

Phase 1: Scope + PluginContext. Later phases add manifest / manager /
discovery. All plugin lifecycle events reuse the single EventBus.
"""

from .context import PluginContext
from .scope import PluginScope

__all__ = ["PluginContext", "PluginScope"]