"""ModelProvider abstraction (spec 14)."""

from .base import ModelProvider, ModelResult, ToolCall
from .mock import MockProvider

__all__ = ["ModelProvider", "ModelResult", "ToolCall", "MockProvider"]