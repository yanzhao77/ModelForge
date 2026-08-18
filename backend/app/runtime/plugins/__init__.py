"""Plugin infrastructure (3.x Composable Agent & Tool Plugin, audit §16).

Scope/Context (P1), Manifest/Manager (P2). All plugin lifecycle events reuse
the single EventBus.
"""

from .context import PluginContext
from .manager import PLUGIN_LIFECYCLE_EVENTS, PluginManager
from .manifest import PluginManifest
from .scope import PluginScope

__all__ = ["PLUGIN_LIFECYCLE_EVENTS", "PluginContext", "PluginManager", "PluginManifest", "PluginScope"]