"""Video generation runtime contracts and safe development runtimes."""
from __future__ import annotations

import asyncio
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Literal, Protocol

VIDEO_CAPABILITY = "video_generation"
VIDEO_CONTRACT_VERSION = "modelforge.video.v1"

VideoStatus = Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCEL_REQUESTED", "CANCELLED", "INTERRUPTED"]
VideoPhase = Literal["accepted", "loading", "inference", "decoding", "encoding", "publishing", "complete"]


class VideoRuntimeError(RuntimeError):
    """Stable, redacted runtime failure."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class VideoProfile:
    profile_id: str
    seconds: int
    fps: int
    width: int
    height: int
    frames: int
    default_steps: int
    min_steps: int
    max_steps: int

    @property
    def size(self) -> str:
        return f"{self.width}x{self.height}"


COGVIDEOX_2B_PROFILE = VideoProfile(
    profile_id="cogvideox2b-t2v-49f-720x480",
    seconds=6,
    fps=8,
    width=720,
    height=480,
    frames=49,
    default_steps=30,
    min_steps=1,
    max_steps=50,
)


@dataclass(frozen=True)
class VideoModelSpec:
    model_id: str
    runtime_name: str
    display_name: str
    upstream_id: str | None = None
    revision: str | None = None
    profiles: tuple[VideoProfile, ...] = (COGVIDEOX_2B_PROFILE,)
    experimental: bool = True
    readiness: str = "unavailable"
    readiness_reason: str | None = None


@dataclass(frozen=True)
class ResolvedVideoGenerationRequest:
    model_id: str
    runtime_name: str
    profile_id: str
    prompt_sha256: str
    seconds: int
    fps: int
    width: int
    height: int
    frames: int
    num_inference_steps: int
    seed: int | None

    @property
    def size(self) -> str:
        return f"{self.width}x{self.height}"

    def public_dict(self) -> dict:
        return {
            "frames": self.frames,
            "fps": self.fps,
            "size": self.size,
            "num_inference_steps": self.num_inference_steps,
            "seed": self.seed,
        }

    def persistence_dict(self) -> dict:
        data = self.public_dict()
        data.update({
            "model": self.model_id,
            "runtime_name": self.runtime_name,
            "profile_id": self.profile_id,
            "prompt_sha256": self.prompt_sha256,
            "contract": VIDEO_CONTRACT_VERSION,
        })
        return data


@dataclass(frozen=True)
class VideoRuntimeProbe:
    available: bool
    code: str
    message: str
    metadata: dict | None = None


@dataclass(frozen=True)
class RuntimeLoadResult:
    status: str
    model_id: str
    runtime_name: str
    metadata: dict | None = None


@dataclass(frozen=True)
class RuntimeStopResult:
    status: str
    model_id: str
    runtime_name: str


@dataclass(frozen=True)
class VideoGenerationResult:
    output_path: Path
    sha256: str
    bytes: int
    duration_ms: int
    metadata: dict | None = None


ProgressCallback = Callable[[VideoPhase, int, int | None], Awaitable[None]]
CancellationToken = Callable[[], bool]


class VideoGenerationRuntime(Protocol):
    runtime_name: str

    async def probe(self, model: VideoModelSpec) -> VideoRuntimeProbe: ...

    async def load(self, model: VideoModelSpec) -> RuntimeLoadResult: ...

    async def generate(
        self,
        request: ResolvedVideoGenerationRequest,
        *,
        progress: ProgressCallback,
        cancellation: CancellationToken,
        output_path: Path,
    ) -> VideoGenerationResult: ...

    async def unload(self, model_id: str) -> RuntimeStopResult: ...

    async def shutdown(self) -> None: ...


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def resolve_video_request(
    *,
    model: VideoModelSpec,
    prompt: str,
    seconds: int,
    fps: int,
    size: str,
    num_inference_steps: int | None,
    seed: int | None,
) -> ResolvedVideoGenerationRequest:
    profile = next((item for item in model.profiles if item.seconds == seconds and item.fps == fps and item.size == size), None)
    if profile is None:
        raise VideoRuntimeError("VIDEO_PROFILE_UNSUPPORTED", "Requested video profile is not supported.")
    steps = profile.default_steps if num_inference_steps is None else num_inference_steps
    if steps < profile.min_steps or steps > profile.max_steps:
        raise VideoRuntimeError("VIDEO_PROFILE_UNSUPPORTED", "Requested inference step count is not supported.")
    return ResolvedVideoGenerationRequest(
        model_id=model.model_id,
        runtime_name=model.runtime_name,
        profile_id=profile.profile_id,
        prompt_sha256=prompt_hash(prompt),
        seconds=profile.seconds,
        fps=profile.fps,
        width=profile.width,
        height=profile.height,
        frames=profile.frames,
        num_inference_steps=steps,
        seed=seed,
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class FakeVideoRuntime:
    """Deterministic no-download runtime used by tests and development."""

    runtime_name = "fake-video"

    async def probe(self, model: VideoModelSpec) -> VideoRuntimeProbe:
        del model
        return VideoRuntimeProbe(True, "READY", "Fake video runtime is available.", {"download_required": False})

    async def load(self, model: VideoModelSpec) -> RuntimeLoadResult:
        await asyncio.sleep(0)
        return RuntimeLoadResult("loaded", model.model_id, self.runtime_name)

    async def generate(
        self,
        request: ResolvedVideoGenerationRequest,
        *,
        progress: ProgressCallback,
        cancellation: CancellationToken,
        output_path: Path,
    ) -> VideoGenerationResult:
        phases: tuple[tuple[VideoPhase, int], ...] = (
            ("loading", 5),
            ("inference", 25),
            ("inference", 50),
            ("decoding", 75),
            ("encoding", 90),
            ("publishing", 98),
        )
        for phase, percent in phases:
            if cancellation():
                raise VideoRuntimeError("VIDEO_CANCELLED", "Video generation was cancelled.")
            await progress(phase, percent, request.num_inference_steps)
            await asyncio.sleep(0.01)
        if cancellation():
            raise VideoRuntimeError("VIDEO_CANCELLED", "Video generation was cancelled.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
            + f"\nModelForge fake video {request.model_id} {request.frames}f {request.size}\n".encode("utf-8")
        )
        output_path.write_bytes(payload)
        await progress("complete", 100, request.num_inference_steps)
        stat = output_path.stat()
        return VideoGenerationResult(
            output_path=output_path,
            sha256=file_sha256(output_path),
            bytes=stat.st_size,
            duration_ms=int(request.frames / request.fps * 1000),
            metadata={"fake": True},
        )

    async def unload(self, model_id: str) -> RuntimeStopResult:
        return RuntimeStopResult("stopped", model_id, self.runtime_name)

    async def shutdown(self) -> None:
        await asyncio.sleep(0)


class CogVideoXRuntimeUnavailable:
    """Probe-only placeholder until video extras and a pinned snapshot are installed."""

    runtime_name = "cogvideox-mps"

    async def probe(self, model: VideoModelSpec) -> VideoRuntimeProbe:
        del model
        try:
            import diffusers  # noqa: F401
            import torch  # noqa: F401
        except Exception:
            return VideoRuntimeProbe(
                False,
                "VIDEO_DEPENDENCIES_MISSING",
                "CogVideoX video dependencies are not installed.",
                {"download_required": False},
            )
        return VideoRuntimeProbe(
            False,
            "VIDEO_MODEL_NOT_INSTALLED",
            "CogVideoX local snapshot has not been installed and benchmarked.",
            {"download_required": True, "mps_fallback": os.getenv("PYTORCH_ENABLE_MPS_FALLBACK")},
        )

    async def load(self, model: VideoModelSpec) -> RuntimeLoadResult:
        raise VideoRuntimeError("VIDEO_RUNTIME_UNAVAILABLE", "CogVideoX runtime is not available.")

    async def generate(
        self,
        request: ResolvedVideoGenerationRequest,
        *,
        progress: ProgressCallback,
        cancellation: CancellationToken,
        output_path: Path,
    ) -> VideoGenerationResult:
        del request, progress, cancellation, output_path
        raise VideoRuntimeError("VIDEO_RUNTIME_UNAVAILABLE", "CogVideoX runtime is not available.")

    async def unload(self, model_id: str) -> RuntimeStopResult:
        return RuntimeStopResult("stopped", model_id, self.runtime_name)

    async def shutdown(self) -> None:
        await asyncio.sleep(0)
