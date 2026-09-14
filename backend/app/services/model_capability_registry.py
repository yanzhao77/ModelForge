"""Capability-oriented model/runtime registry."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from services.runtime_registry import RuntimeRegistry
from services.video_runtime import (
    COGVIDEOX_2B_PROFILE,
    VIDEO_CAPABILITY,
    CogVideoXRuntimeUnavailable,
    FakeVideoRuntime,
    VideoGenerationRuntime,
    VideoModelSpec,
)


class CapabilityRegistryError(ValueError):
    pass


class ChatRuntimeAdapter:
    """Thin adapter for the existing chat RuntimeRegistry."""

    capability = "chat"

    def __init__(self, registry: RuntimeRegistry | None = None) -> None:
        self.registry = registry or RuntimeRegistry()

    def metadata(self) -> dict[str, Any]:
        status = self.registry.status() if hasattr(self.registry, "status") else {}
        return {"capability": self.capability, "status": status}


class ModelCapabilityRegistry:
    """Resolve runtimes by explicit model capability and runtime name."""

    def __init__(self) -> None:
        self._chat: dict[str, ChatRuntimeAdapter] = {}
        self._video_models: dict[str, VideoModelSpec] = {}
        self._video_runtimes: dict[str, VideoGenerationRuntime] = {}

    def register_chat(self, name: str, adapter: ChatRuntimeAdapter) -> None:
        if name in self._chat:
            raise CapabilityRegistryError(f"duplicate chat runtime: {name}")
        self._chat[name] = adapter

    def register_video_model(self, model: VideoModelSpec, runtime: VideoGenerationRuntime) -> None:
        if model.model_id in self._video_models:
            raise CapabilityRegistryError(f"duplicate video model: {model.model_id}")
        if model.runtime_name != runtime.runtime_name:
            raise CapabilityRegistryError("video model runtime_name does not match runtime")
        self._video_models[model.model_id] = model
        self._video_runtimes[model.runtime_name] = runtime

    def video_model(self, model_id: str) -> VideoModelSpec | None:
        return self._video_models.get(model_id)

    def video_models(self) -> list[VideoModelSpec]:
        return list(self._video_models.values())

    def video_runtime(self, model: VideoModelSpec) -> VideoGenerationRuntime:
        runtime = self._video_runtimes.get(model.runtime_name)
        if runtime is None:
            raise CapabilityRegistryError(f"unknown video runtime: {model.runtime_name}")
        return runtime

    def metadata(self) -> dict:
        return {
            "capabilities": {
                "chat": sorted(self._chat),
                VIDEO_CAPABILITY: [model.model_id for model in self.video_models()],
            }
        }


def build_default_capability_registry() -> ModelCapabilityRegistry:
    registry = ModelCapabilityRegistry()
    registry.register_chat("default", ChatRuntimeAdapter())
    registry.register_video_model(
        VideoModelSpec(
            model_id="fake-video",
            runtime_name="fake-video",
            display_name="Fake Video Runtime",
            profiles=(COGVIDEOX_2B_PROFILE,),
            experimental=True,
            readiness="ready",
        ),
        FakeVideoRuntime(),
    )
    registry.register_video_model(
        VideoModelSpec(
            model_id="cogvideox-2b",
            runtime_name="cogvideox-mps",
            display_name="CogVideoX-2B",
            upstream_id="zai-org/CogVideoX-2b",
            revision=None,
            profiles=(COGVIDEOX_2B_PROFILE,),
            experimental=True,
            readiness="unavailable",
            readiness_reason="Phase 0 benchmark and managed local snapshot are not present.",
        ),
        CogVideoXRuntimeUnavailable(),
    )
    return registry


_registry: ModelCapabilityRegistry | None = None


def get_capability_registry() -> ModelCapabilityRegistry:
    global _registry
    if _registry is None:
        _registry = build_default_capability_registry()
    return _registry


def set_capability_registry(registry: ModelCapabilityRegistry | None) -> None:
    global _registry
    _registry = registry


async def probed_video_models() -> list[VideoModelSpec]:
    """Return video specs with readiness updated from side-effect-free probes."""
    registry = get_capability_registry()
    result: list[VideoModelSpec] = []
    for model in registry.video_models():
        probe = await registry.video_runtime(model).probe(model)
        readiness = "ready" if probe.available else "unavailable"
        result.append(replace(model, readiness=readiness, readiness_reason=probe.message))
    return result
