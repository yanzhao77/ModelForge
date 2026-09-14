"""Local Diffusers Wan text-to-video runtime.

The runtime is intentionally narrow: it only accepts an already-authorized
local Wan Diffusers snapshot and runs it offline in a child process.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import multiprocessing as mp
import os
import queue
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from services.video_runtime import (
    RuntimeLoadResult,
    RuntimeStopResult,
    VideoGenerationResult,
    VideoModelSpec,
    VideoRuntimeError,
    VideoRuntimeProbe,
    file_sha256,
)

WAN_RUNTIME_NAME = "wan-diffusers"
WAN_COMPONENTS = {
    "scheduler": ("UniPCMultistepScheduler", "scheduler_config.json", ()),
    "text_encoder": ("UMT5EncoderModel", "config.json", ("model.safetensors", "model.safetensors.index.json")),
    "tokenizer": ("T5TokenizerFast", "tokenizer_config.json", ("tokenizer.json", "spiece.model")),
    "transformer": ("WanTransformer3DModel", "config.json", ("diffusion_pytorch_model.safetensors", "diffusion_pytorch_model.safetensors.index.json")),
    "vae": ("AutoencoderKLWan", "config.json", ("diffusion_pytorch_model.safetensors", "diffusion_pytorch_model.safetensors.index.json")),
}
WAN_DEPENDENCIES = ("torch", "diffusers", "transformers", "accelerate", "imageio", "safetensors", "sentencepiece")
_MAX_SWAP_GROWTH_MB = 4096.0


def _json_read(path: Path) -> tuple[dict | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "missing"
    except (OSError, ValueError) as exc:
        return None, type(exc).__name__
    return (payload, None) if isinstance(payload, dict) else (None, "not_object")


def missing_wan_dependencies() -> list[str]:
    missing: list[str] = []
    for module in WAN_DEPENDENCIES:
        try:
            if importlib.util.find_spec(module) is None:
                missing.append(module)
        except (ImportError, ValueError):
            missing.append(module)
    return missing


def validate_wan_diffusers_snapshot(path: str | Path) -> dict[str, Any]:
    """Validate required Wan Diffusers files without importing model code."""
    root = Path(path).expanduser().resolve()
    result: dict[str, Any] = {
        "ok": False,
        "path": str(root),
        "pipeline": None,
        "components": {},
        "missing_files": [],
        "errors": [],
        "total_indexed_weight_bytes": 0,
    }
    model_index, err = _json_read(root / "model_index.json")
    if err:
        result["errors"].append(f"model_index.json:{err}")
        result["missing_files"].append("model_index.json")
        return result
    pipeline = str((model_index or {}).get("_class_name") or "")
    result["pipeline"] = pipeline
    if pipeline != "WanPipeline":
        result["errors"].append(f"unsupported_pipeline:{pipeline or 'unknown'}")
    for component, (expected_class, config_name, weight_markers) in WAN_COMPONENTS.items():
        declaration = model_index.get(component) if isinstance(model_index, dict) else None
        declared_class = declaration[1] if isinstance(declaration, list) and len(declaration) > 1 else None
        info = {"declared_class": declared_class, "expected_class": expected_class, "weights": []}
        result["components"][component] = info
        if declared_class != expected_class:
            result["errors"].append(f"{component}:class:{declared_class or 'missing'}")
        component_dir = root / component
        if not component_dir.is_dir():
            result["missing_files"].append(component)
            continue
        if not (component_dir / config_name).is_file():
            result["missing_files"].append(f"{component}/{config_name}")
        marker_found = not weight_markers
        for marker in weight_markers:
            marker_path = component_dir / marker
            if not marker_path.exists():
                continue
            marker_found = True
            if marker.endswith(".index.json"):
                index, index_err = _json_read(marker_path)
                if index_err:
                    result["errors"].append(f"{component}/{marker}:{index_err}")
                    continue
                total_size = ((index or {}).get("metadata") or {}).get("total_size")
                if isinstance(total_size, int):
                    result["total_indexed_weight_bytes"] += total_size
                weight_map = (index or {}).get("weight_map")
                if not isinstance(weight_map, dict) or not weight_map:
                    result["errors"].append(f"{component}/{marker}:missing_weight_map")
                    continue
                for shard in sorted({str(value) for value in weight_map.values()}):
                    shard_path = component_dir / shard
                    info["weights"].append(shard)
                    if not shard_path.is_file():
                        result["missing_files"].append(f"{component}/{shard}")
            elif marker_path.is_file():
                info["weights"].append(marker)
        if not marker_found:
            result["missing_files"].append(f"{component}/weights")
    result["missing_files"] = sorted(set(result["missing_files"]))
    result["errors"] = sorted(set(result["errors"]))
    result["ok"] = not result["missing_files"] and not result["errors"]
    return result


def _mps_probe() -> tuple[bool, dict[str, Any]]:
    try:
        import torch
    except Exception as exc:  # pragma: no cover - dependency path
        return False, {"error": type(exc).__name__}
    available = bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())
    metadata = {
        "mps_available": available,
        "mps_built": bool(getattr(torch.backends.mps, "is_built", lambda: False)()),
        "mps_fallback": os.getenv("PYTORCH_ENABLE_MPS_FALLBACK"),
    }
    if available:
        try:
            tensor = torch.ones((1,), device="mps", dtype=torch.bfloat16)
            metadata["bf16_smoke"] = float(tensor.cpu()[0]) == 1.0
        except Exception as exc:
            metadata["bf16_smoke"] = False
            metadata["bf16_error"] = type(exc).__name__
    return available and metadata.get("bf16_smoke") is not False, metadata


def _swap_used_mb() -> float | None:
    try:
        output = subprocess.check_output(["sysctl", "vm.swapusage"], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return None
    match = re.search(r"used = ([0-9.]+)M", output)
    return float(match.group(1)) if match else None


def _process_rss_mb(pid: int) -> float | None:
    try:
        output = subprocess.check_output(["ps", "-o", "rss=", "-p", str(pid)], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None
    try:
        return int(output or "0") / 1024.0
    except ValueError:
        return None


class WanDiffusersVideoRuntime:
    runtime_name = WAN_RUNTIME_NAME

    def __init__(self, worker_main=None) -> None:
        self._worker_main = worker_main or _wan_worker_main

    async def probe(self, model: VideoModelSpec) -> VideoRuntimeProbe:
        if not model.local_path:
            return VideoRuntimeProbe(False, "VIDEO_MODEL_PATH_MISSING", "Wan model path is not registered.")
        validation = validate_wan_diffusers_snapshot(model.local_path)
        if not validation["ok"]:
            return VideoRuntimeProbe(False, "VIDEO_MODEL_FILES_INVALID", "Wan model files are incomplete or invalid.", validation)
        missing = missing_wan_dependencies()
        if missing:
            return VideoRuntimeProbe(False, "VIDEO_DEPENDENCIES_MISSING", "Wan video dependencies are not installed.", {"missing_dependencies": missing, "validation": validation})
        mps_ok, mps_metadata = _mps_probe()
        if not mps_ok:
            return VideoRuntimeProbe(False, "VIDEO_MPS_UNAVAILABLE", "Apple MPS with BF16 support is not available for Wan generation.", {"mps": mps_metadata, "validation": validation})
        return VideoRuntimeProbe(True, "READY", "Wan Diffusers runtime is available.", {"mps": mps_metadata, "validation": validation})

    async def load(self, model: VideoModelSpec) -> RuntimeLoadResult:
        probe = await self.probe(model)
        if not probe.available:
            raise VideoRuntimeError(probe.code, probe.message)
        return RuntimeLoadResult("loadable", model.model_id, self.runtime_name, probe.metadata)

    async def generate(self, request, *, progress, cancellation, output_path: Path) -> VideoGenerationResult:
        return await asyncio.to_thread(self._generate_blocking, request, progress, cancellation, output_path)

    def _generate_blocking(self, request, progress, cancellation, output_path: Path) -> VideoGenerationResult:
        model_path = getattr(request, "local_path", None)
        if model_path is None:
            raise VideoRuntimeError("VIDEO_MODEL_PATH_MISSING", "Wan model path is not attached to the generation request.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        ctx = mp.get_context("spawn")
        events = ctx.Queue()
        proc = ctx.Process(
            target=self._worker_main,
            args=(model_path, request.prompt, request.num_inference_steps, request.frames, request.height, request.width, request.fps, request.seed, str(output_path), events),
            daemon=True,
        )
        proc.start()
        duration_ms = int(request.frames / request.fps * 1000)
        swap_start = _swap_used_mb()
        peak_rss = 0.0
        peak_swap = swap_start or 0.0
        try:
            while proc.is_alive() or not events.empty():
                if cancellation():
                    proc.terminate()
                    proc.join(timeout=10)
                    raise VideoRuntimeError("VIDEO_CANCELLED", "Video generation was cancelled.")
                rss = _process_rss_mb(proc.pid)
                swap = _swap_used_mb()
                if rss is not None:
                    peak_rss = max(peak_rss, rss)
                if swap is not None:
                    peak_swap = max(peak_swap, swap)
                if swap_start is not None and swap is not None and swap - swap_start > _MAX_SWAP_GROWTH_MB:
                    proc.terminate()
                    proc.join(timeout=10)
                    raise VideoRuntimeError(
                        "VIDEO_RESOURCE_PRESSURE",
                        f"Wan generation stopped because swap grew by more than {int(_MAX_SWAP_GROWTH_MB)} MB.",
                    )
                try:
                    event = events.get(timeout=0.25)
                except queue.Empty:
                    continue
                kind = event.get("type")
                if kind == "progress":
                    asyncio.run(progress(event.get("phase", "inference"), int(event.get("percent", 0)), event.get("total")))
                elif kind == "complete":
                    duration_ms = int(event.get("duration_ms") or duration_ms)
                elif kind == "error":
                    raise VideoRuntimeError(str(event.get("code") or "VIDEO_GENERATION_FAILED"), str(event.get("message") or "Video generation failed."))
            proc.join(timeout=1)
        finally:
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=5)
        if proc.exitcode not in (0, None):
            raise VideoRuntimeError("VIDEO_WORKER_FAILED", "Wan generation process exited before producing a valid video.")
        if not output_path.is_file() or output_path.stat().st_size <= 0:
            raise VideoRuntimeError("VIDEO_ARTIFACT_MISSING", "Wan generation did not produce an MP4 artifact.")
        sha = file_sha256(output_path)
        return VideoGenerationResult(output_path, sha, output_path.stat().st_size, duration_ms, {"runtime": self.runtime_name, "peak_rss_mb": peak_rss, "peak_swap_mb": peak_swap})

    async def unload(self, model_id: str) -> RuntimeStopResult:
        return RuntimeStopResult("stopped", model_id, self.runtime_name)

    async def shutdown(self) -> None:
        await asyncio.sleep(0)


def _wan_worker_main(model_path: str, prompt: str, steps: int, frames: int, height: int, width: int, fps: int, seed: int | None, output_path: str, events) -> None:
    started = time.monotonic()
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("DIFFUSERS_OFFLINE", "1")
    try:
        import imageio.v2 as imageio
        import torch
        from diffusers import AutoencoderKLWan, WanPipeline
        from diffusers.utils import export_to_video

        validation = validate_wan_diffusers_snapshot(model_path)
        if not validation["ok"]:
            events.put({"type": "error", "code": "VIDEO_MODEL_FILES_INVALID", "message": "Wan model files are incomplete or invalid."})
            return
        if not (getattr(torch.backends, "mps", None) and torch.backends.mps.is_available()):
            events.put({"type": "error", "code": "VIDEO_MPS_UNAVAILABLE", "message": "Apple MPS is not available."})
            return
        events.put({"type": "progress", "phase": "loading", "percent": 5, "total": steps})
        vae = AutoencoderKLWan.from_pretrained(model_path, subfolder="vae", torch_dtype=torch.float32, local_files_only=True)
        pipe = WanPipeline.from_pretrained(model_path, vae=vae, torch_dtype=torch.bfloat16, local_files_only=True)
        pipe.enable_model_cpu_offload(device="mps")
        pipe.vae.enable_slicing()
        pipe.vae.enable_tiling()

        def callback(_pipe, step_index, timestep, callback_kwargs):
            del _pipe, timestep
            percent = 10 + int(((step_index + 1) / max(steps, 1)) * 75)
            events.put({"type": "progress", "phase": "inference", "percent": percent, "total": steps})
            return callback_kwargs

        generator = torch.Generator(device="mps")
        if seed is not None:
            generator.manual_seed(int(seed))
        output = pipe(
            prompt=prompt,
            num_videos_per_prompt=1,
            num_inference_steps=int(steps),
            num_frames=int(frames),
            height=int(height),
            width=int(width),
            guidance_scale=5.0,
            generator=generator,
            callback_on_step_end=callback,
        )
        events.put({"type": "progress", "phase": "encoding", "percent": 92, "total": steps})
        export_to_video(output.frames[0], output_path, fps=int(fps))
        events.put({"type": "progress", "phase": "publishing", "percent": 98, "total": steps})
        reader = imageio.get_reader(output_path, "ffmpeg")
        try:
            next(iter(reader))
        finally:
            reader.close()
        events.put({"type": "complete", "duration_ms": int((time.monotonic() - started) * 1000)})
    except BaseException as exc:  # noqa: BLE001 - child boundary must report structured error
        events.put({"type": "error", "code": "VIDEO_GENERATION_FAILED", "message": f"{type(exc).__name__}: {exc}"})
