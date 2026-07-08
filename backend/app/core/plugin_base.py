"""Plugin System - Service Provider Interface (SPI)."""
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional


class Plugin(ABC):
    """Abstract base class for all ModelForge plugins."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique plugin name."""
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """Plugin version string."""
        ...

    @property
    @abstractmethod
    def plugin_type(self) -> str:
        """Plugin type: model, tool, runtime."""
        ...

    @abstractmethod
    def install(self) -> bool:
        """Install/initialize the plugin. Returns True on success."""
        ...

    @abstractmethod
    def execute(self, **kwargs) -> Any:
        """Execute the plugin with given parameters."""
        ...

    def get_info(self) -> Dict:
        """Get plugin metadata."""
        return {
            "name": self.name,
            "version": self.version,
            "type": self.plugin_type,
        }


class ModelPlugin(Plugin):
    """Plugin for model-related functionality."""

    @property
    def plugin_type(self) -> str:
        return "model"

    @abstractmethod
    def get_supported_formats(self) -> List[str]:
        """Return list of supported model formats."""
        ...


class ToolPlugin(Plugin):
    """Plugin providing a tool for agents."""

    @property
    def plugin_type(self) -> str:
        return "tool"

    @abstractmethod
    def get_tool_spec(self) -> Dict:
        """Return the OpenAPI-like tool specification."""
        ...


class RuntimePlugin(Plugin):
    """Plugin providing a model runtime backend."""

    @property
    def plugin_type(self) -> str:
        return "runtime"

    @abstractmethod
    def get_supported_models(self) -> List[str]:
        """Return list of supported model identifiers."""
        ...