"""Plugin infrastructure (3.x Composable Agent & Tool Plugin, audit §16).

Scope/Context (P1), Manifest/Manager (P2). All plugin lifecycle events reuse
the single EventBus.
"""

from .context import PluginContext
from .manager import PluginManager, PLUGIN_LIFECYCLE_EVENTS
from .manifest import PluginManifest
from .scope import PluginScope

__all__ = ["PluginContext", "PluginManager", "PluginManifest", "PluginScope", "PLUGIN_LIFECYCLE_EVENTS"]