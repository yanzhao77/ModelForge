"""Phase 10: Plugin System tests."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from core.plugin_base import Plugin, ModelPlugin, ToolPlugin, RuntimePlugin
from services.plugin_manager import PluginManager


class DummyModelPlugin(ModelPlugin):
    """A test model plugin."""

    @property
    def name(self) -> str:
        return "dummy-model"

    @property
    def version(self) -> str:
        return "1.0.0"

    def install(self) -> bool:
        return True

    def execute(self, **kwargs):
        return {"action": "model", "kwargs": kwargs}

    def get_supported_formats(self):
        return ["gguf", "safetensors"]


class DummyToolPlugin(ToolPlugin):
    """A test tool plugin."""

    @property
    def name(self) -> str:
        return "dummy-tool"

    @property
    def version(self) -> str:
        return "0.1.0"

    def install(self) -> bool:
        return True

    def execute(self, **kwargs):
        return {"tool": "dummy", "input": kwargs}

    def get_tool_spec(self):
        return {"name": "dummy", "description": "A test tool"}


class DummyRuntimePlugin(RuntimePlugin):
    """A test runtime plugin."""

    @property
    def name(self) -> str:
        return "dummy-runtime"

    @property
    def version(self) -> str:
        return "2.0.0"

    def install(self) -> bool:
        return False  # Simulates install failure

    def execute(self, **kwargs):
        return {"runtime": "dummy"}

    def get_supported_models(self):
        return ["model-a", "model-b"]


class TestPluginBase:
    """Tests for the abstract plugin base classes."""

    def test_cannot_instantiate_plugin(self):
        with pytest.raises(TypeError):
            Plugin()

    def test_cannot_instantiate_model_plugin(self):
        with pytest.raises(TypeError):
            ModelPlugin()

    def test_concrete_plugin_works(self):
        p = DummyModelPlugin()
        assert p.name == "dummy-model"
        assert p.version == "1.0.0"
        assert p.plugin_type == "model"

    def test_get_info(self):
        p = DummyToolPlugin()
        info = p.get_info()
        assert info["name"] == "dummy-tool"
        assert info["type"] == "tool"


class TestPluginManager:
    """Tests for the plugin manager."""

    def test_register(self):
        pm = PluginManager()
        assert pm.register(DummyModelPlugin()) is True
        assert pm.count() == 1

    def test_register_duplicate(self):
        pm = PluginManager()
        pm.register(DummyModelPlugin())
        assert pm.register(DummyModelPlugin()) is False

    def test_unregister(self):
        pm = PluginManager()
        pm.register(DummyToolPlugin())
        assert pm.unregister("dummy-tool") is True
        assert pm.count() == 0

    def test_unregister_nonexistent(self):
        pm = PluginManager()
        assert pm.unregister("nonexistent") is False

    def test_get(self):
        pm = PluginManager()
        pm.register(DummyModelPlugin())
        p = pm.get("dummy-model")
        assert p is not None
        assert p.name == "dummy-model"

    def test_get_nonexistent(self):
        pm = PluginManager()
        assert pm.get("nope") is None

    def test_list_all(self):
        pm = PluginManager()
        pm.register(DummyModelPlugin())
        pm.register(DummyToolPlugin())
        plugins = pm.list_all()
        assert len(plugins) == 2

    def test_list_by_type(self):
        pm = PluginManager()
        pm.register(DummyModelPlugin())
        pm.register(DummyToolPlugin())
        pm.register(DummyRuntimePlugin())
        models = pm.list_by_type("model")
        tools = pm.list_by_type("tool")
        runtimes = pm.list_by_type("runtime")
        assert len(models) == 1
        assert len(tools) == 1
        assert len(runtimes) == 1

    def test_install_all(self):
        pm = PluginManager()
        pm.register(DummyModelPlugin())
        pm.register(DummyRuntimePlugin())
        results = pm.install_all()
        assert results["dummy-model"] is True
        assert results["dummy-runtime"] is False

    def test_execute(self):
        pm = PluginManager()
        pm.register(DummyToolPlugin())
        result = pm.execute("dummy-tool", input_data="test")
        assert result["status"] == "ok"
        assert result["result"]["tool"] == "dummy"

    def test_execute_nonexistent(self):
        pm = PluginManager()
        result = pm.execute("nope")
        assert "error" in result

    def test_count(self):
        pm = PluginManager()
        assert pm.count() == 0
        pm.register(DummyModelPlugin())
        assert pm.count() == 1