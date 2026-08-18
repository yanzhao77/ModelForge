"""ModelProvider abstraction (spec 14)."""

from .base import ModelProvider, ModelResult, ToolCall
from .mock import MockProvider

__all__ = ["MockProvider", "ModelProvider", "ModelResult", "ToolCall"]