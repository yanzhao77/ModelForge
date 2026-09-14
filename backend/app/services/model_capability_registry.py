"""Capability-oriented model/runtime registry."""
from __future__ import annotations

import os
from dataclasses import replace
from typing import Any

from services.runtime_registry import RuntimeRegistry
from services.video_runtime import (
    COGVIDEOX_2B_PROFILE,
    VIDEO_CAPABILITY,
    WAN21_MPS_SHORT_PROFILE,
    WAN21_MPS_SMOKE_PROFILE,
    CogVideoXRuntimeUnavailable,
    FakeVideoRuntime,
    VideoGenerationRuntime,
    VideoModelSpec,
)
from services.wan_video_runtime import WAN_RUNTIME_NAME, WanDiffusersVideoRuntime


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

    def register_video_runtime(self, runtime: VideoGenerationRuntime) -> None:
        self._video_runtimes[runtime.runtime_name] = runtime

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
    registry.register_video_runtime(WanDiffusersVideoRuntime())
    if os.getenv("MODELFORGE_ENABLE_FAKE_VIDEO_RUNTIME") == "1":
        registry.register_video_model(
            VideoModelSpec(
                model_id="fake-video",
                runtime_name="fake-video",
                display_name="Fake Video Runtime",
                profiles=(COGVIDEOX_2B_PROFILE,),
                experimental=True,
                readiness="ready",
                readiness_code="READY",
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
            readiness_code="VIDEO_MODEL_NOT_INSTALLED",
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
        result.append(replace(model, readiness=readiness, readiness_code=probe.code, readiness_reason=probe.message))
    return result


def _is_wan_record(record) -> bool:
    metadata = record.metadata_dict() if hasattr(record, "metadata_dict") else {}
    model_index = metadata.get("model_index") if isinstance(metadata, dict) else None
    class_name = str((model_index or {}).get("_class_name") or metadata.get("architecture") or "")
    if class_name != "WanPipeline":
        return False
    caps = record.capability_list() if hasattr(record, "capability_list") else []
    return "VIDEO" in {str(item).upper() for item in caps}


def video_spec_from_record(record) -> VideoModelSpec | None:
    if not _is_wan_record(record):
        return None
    return VideoModelSpec(
        model_id=f"local:{record.id}",
        runtime_name=WAN_RUNTIME_NAME,
        display_name=record.display_name or record.name,
        upstream_id="Wan-AI/Wan2.1-T2V-1.3B-Diffusers",
        profiles=(WAN21_MPS_SMOKE_PROFILE, WAN21_MPS_SHORT_PROFILE),
        experimental=True,
        readiness="unavailable",
        readiness_code=None,
        readiness_reason=None,
        local_model_id=record.id,
        local_path=record.path,
        owner_user_id=record.user_id,
    )


def resolve_video_model(db, user_id: int, model_id: str) -> VideoModelSpec | None:
    registry = get_capability_registry()
    static = registry.video_model(model_id)
    if static is not None:
        return static
    from services.local_api_service import LocalApiService
    from services.model_registry import ModelRegistry

    lookup = str(model_id or "").strip()
    if lookup.startswith("local:"):
        lookup = lookup.split(":", 1)[1]
    record = LocalApiService(db).resolve_model(user_id, lookup)
    if record is not None:
        ModelRegistry(db).repair_detected_local_record(record, commit=True)
    spec = video_spec_from_record(record) if record is not None else None
    if spec is None or record is None:
        return spec
    metadata = record.metadata_dict()
    local_import = metadata.get("local_import") if isinstance(metadata, dict) else {}
    load_validation = local_import.get("load_validation") if isinstance(local_import, dict) else None
    if isinstance(load_validation, dict) and load_validation.get("status") == "failed":
        return replace(
            spec,
            readiness="unavailable",
            readiness_code="VIDEO_LOAD_VALIDATION_FAILED",
            readiness_reason=str(load_validation.get("message") or "Wan load validation has not passed."),
        )
    return spec


async def user_video_models(db, user_id: int) -> list[VideoModelSpec]:
    from services.model_capabilities import ModelCapability
    from services.model_registry import ModelRegistry

    registry = get_capability_registry()
    result = await probed_video_models()
    for record in ModelRegistry(db).list_models(user_id, capability=ModelCapability.VIDEO.value):
        spec = video_spec_from_record(record)
        if spec is None:
            continue
        probe = await registry.video_runtime(spec).probe(spec)
        readiness = "ready" if probe.available else "unavailable"
        metadata = record.metadata_dict()
        local_import = metadata.get("local_import") if isinstance(metadata, dict) else {}
        load_validation = local_import.get("load_validation") if isinstance(local_import, dict) else None
        if isinstance(load_validation, dict) and load_validation.get("status") == "failed":
            readiness = "unavailable"
            code = "VIDEO_LOAD_VALIDATION_FAILED"
            reason = str(load_validation.get("message") or "Wan load validation has not passed.")
        else:
            code = probe.code
            reason = probe.message
        result.append(replace(spec, readiness=readiness, readiness_code=code, readiness_reason=reason))
    return result


def _video_state(model: VideoModelSpec) -> dict[str, str | bool]:
    code = model.readiness_code
    dependencies = "check_required"
    if code == "VIDEO_DEPENDENCIES_MISSING":
        dependencies = "missing"
    elif code:
        dependencies = "available"
    runtime = "loadable" if model.readiness == "ready" else "unavailable"
    if code == "VIDEO_LOAD_VALIDATION_FAILED":
        runtime = "load_failed"
    elif code == "VIDEO_MODEL_FILES_INVALID":
        runtime = "files_invalid"
    elif code == "VIDEO_DEPENDENCIES_MISSING":
        runtime = "dependencies_missing"
    elif code == "VIDEO_MPS_UNAVAILABLE":
        runtime = "hardware_unavailable"
    return {
        "files": "registered" if model.local_path else "built_in",
        "dependencies": dependencies,
        "runtime": runtime,
        "loaded": False,
    }


async def video_model_descriptors(db=None, user_id: int | None = None) -> list[dict]:
    """Share the probed video catalog across desktop and API-key transports."""
    models = await user_video_models(db, user_id) if db is not None and user_id is not None else await probed_video_models()
    return [
        {
            "id": model.model_id,
            "object": "model",
            "owned_by": "local",
            "modelforge": {
                "contract": "modelforge.video.v1",
                "capabilities": [VIDEO_CAPABILITY],
                "readiness": model.readiness,
                "readiness_code": model.readiness_code,
                "readiness_reason": model.readiness_reason,
                "runtime": model.runtime_name,
                "registry_model_id": model.local_model_id,
                "state": _video_state(model),
                "upstream_id": model.upstream_id,
                "experimental": model.experimental,
                "profiles": [
                    {
                        "id": profile.profile_id,
                        "seconds": profile.seconds,
                        "fps": profile.fps,
                        "size": profile.size,
                        "frames": profile.frames,
                        "default_steps": profile.default_steps,
                        "min_steps": profile.min_steps,
                        "max_steps": profile.max_steps,
                    }
                    for profile in model.profiles
                ],
            },
        }
        for model in models
    ]
