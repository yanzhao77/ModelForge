"""Phase 0 Wan2.1 T2V 1.3B MPS feasibility benchmark.

This benchmark is intentionally isolated from production code. It never
downloads models and always loads the pinned local snapshot with
``local_files_only=True``. Each scenario writes one JSON result atomically after
important boundaries so partial evidence survives failures, OOMs, and user
interrupts.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable


MODEL_ID = "Wan-AI/Wan2.1-T2V-1.3B-Diffusers"
REVISION = "0fad780a534b6463e45facd96134c9f345acfa5b"
DEFAULT_SNAPSHOT = "benchmarks/wan21_phase0/output/snapshot"
DEFAULT_OUTPUT = "benchmarks/wan21_phase0/output"
DEFAULT_PROMPT = "A futuristic submarine cruising through the deep ocean, cinematic lighting, smooth camera movement"
DEFAULT_FRAMES = 81
DEFAULT_FPS = 15
DEFAULT_HEIGHT = 480
DEFAULT_WIDTH = 832
DEFAULT_STEPS = 50
DEFAULT_SEED = 12345
DEFAULT_GUIDANCE_SCALE = 5.0


class ScenarioCancelled(Exception):
    """Raised from the diffusion callback to exercise cancellation."""


@dataclass
class Timing:
    name: str
    started_at: str
    start_perf_s: float
    ended_at: str | None = None
    end_perf_s: float | None = None

    @property
    def duration_s(self) -> float | None:
        if self.end_perf_s is None:
            return None
        return round(self.end_perf_s - self.start_perf_s, 3)

    def finish(self) -> None:
        self.ended_at = _now_iso()
        self.end_perf_s = time.perf_counter()

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["duration_s"] = self.duration_s
        return data


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT).strip()
    except Exception as exc:
        return f"unavailable: {exc}"


def _version(name: str) -> str | None:
    try:
        module = __import__(name)
        return str(getattr(module, "__version__", "unknown"))
    except Exception:
        return None


def _sanitize_argv(argv: list[str]) -> list[str]:
    sanitized: list[str] = []
    skip_next = False
    for item in argv:
        if skip_next:
            sanitized.append("<redacted-prompt>")
            skip_next = False
            continue
        if item == "--prompt":
            sanitized.append(item)
            skip_next = True
            continue
        if item.startswith("--prompt="):
            sanitized.append("--prompt=<redacted-prompt>")
            continue
        sanitized.append(item)
    return sanitized


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _mps_metrics(torch_module: Any) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    mps = getattr(torch_module, "mps", None)
    if mps is None:
        return metrics
    for name in ("current_allocated_memory", "driver_allocated_memory", "recommended_max_memory"):
        fn = getattr(mps, name, None)
        if callable(fn):
            try:
                metrics[name] = int(fn())
            except Exception as exc:
                metrics[name] = {"error": str(exc)}
    return metrics


def _rss_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.Process().memory_info().rss)
    except Exception:
        return None


def _system_memory() -> dict[str, Any]:
    data: dict[str, Any] = {}
    try:
        import psutil

        vm = psutil.virtual_memory()
        swap = psutil.swap_memory()
        data["virtual_memory"] = {
            "total": int(vm.total),
            "available": int(vm.available),
            "used": int(vm.used),
            "percent": float(vm.percent),
        }
        data["swap"] = {
            "total": int(swap.total),
            "used": int(swap.used),
            "free": int(swap.free),
            "percent": float(swap.percent),
            "sin": int(getattr(swap, "sin", 0)),
            "sout": int(getattr(swap, "sout", 0)),
        }
    except Exception as exc:
        data["psutil_error"] = str(exc)
    data["vm_stat"] = _run(["vm_stat"])
    return data


def _memory_sample(torch_module: Any, label: str) -> dict[str, Any]:
    sample = {
        "label": label,
        "timestamp": _now_iso(),
        "perf_s": time.perf_counter(),
        "rss_bytes": _rss_bytes(),
        "mps": _mps_metrics(torch_module),
        "system": _system_memory(),
    }
    return sample


def _numeric_values(samples: list[dict[str, Any]], path: tuple[str, ...]) -> list[int | float]:
    values: list[int | float] = []
    for sample in samples:
        current: Any = sample
        for part in path:
            if not isinstance(current, dict) or part not in current:
                current = None
                break
            current = current[part]
        if isinstance(current, (int, float)) and not isinstance(current, bool):
            values.append(current)
    return values


def _peaks(samples: list[dict[str, Any]]) -> dict[str, Any]:
    peak_paths = {
        "rss_bytes": ("rss_bytes",),
        "mps_current_allocated_memory": ("mps", "current_allocated_memory"),
        "mps_driver_allocated_memory": ("mps", "driver_allocated_memory"),
        "mps_recommended_max_memory": ("mps", "recommended_max_memory"),
        "swap_used": ("system", "swap", "used"),
        "swap_percent": ("system", "swap", "percent"),
        "virtual_memory_percent": ("system", "virtual_memory", "percent"),
    }
    result: dict[str, Any] = {}
    for name, path in peak_paths.items():
        values = _numeric_values(samples, path)
        result[name] = max(values) if values else None
    return result


class MemorySampler:
    def __init__(self, torch_module: Any, *, interval_s: float) -> None:
        self.torch = torch_module
        self.interval_s = interval_s
        self.samples: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.boundary("sampler_start")
        self._thread = threading.Thread(target=self._run, name="phase0-memory-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(2.0, self.interval_s * 2))
        self.boundary("sampler_stop")

    def _run(self) -> None:
        while not self._stop.wait(self.interval_s):
            self.boundary("interval")

    def boundary(self, label: str) -> dict[str, Any]:
        sample = _memory_sample(self.torch, label)
        with self._lock:
            self.samples.append(sample)
        return sample

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.samples)


def _classify_error(exc: BaseException) -> dict[str, Any]:
    text = f"{type(exc).__name__}: {exc}"
    lower = text.lower()
    categories: list[str] = []
    if "out of memory" in lower or "oom" in lower or "mps backend out of memory" in lower:
        categories.append("mps_oom")
    if "unsupported" in lower and ("mps" in lower or "operator" in lower or "op" in lower):
        categories.append("unsupported_operator")
    if "mps" in lower and ("float64" in lower or "doesn't support" in lower):
        categories.append("mps_dtype_unsupported")
    if "fallback" in lower:
        categories.append("cpu_fallback")
    if "nan" in lower or "inf" in lower:
        categories.append("nan_or_inf")
    if "ffmpeg" in lower or "export" in lower or "video" in lower:
        categories.append("export_or_video")
    if isinstance(exc, KeyboardInterrupt):
        categories.append("user_interrupt")
    if not categories:
        categories.append("other")
    return {
        "type": type(exc).__name__,
        "message": str(exc)[:2000],
        "categories": categories,
        "traceback_tail": traceback.format_exc(limit=8)[-4000:],
    }


def _host_and_packages() -> dict[str, Any]:
    return {
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "macos": _run(["sw_vers"]),
            "cpu_brand": _run(["sysctl", "-n", "machdep.cpu.brand_string"]),
            "mem_bytes": _run(["sysctl", "-n", "hw.memsize"]),
            "python": sys.version,
        },
        "packages": {
            "torch": _version("torch"),
            "diffusers": _version("diffusers"),
            "transformers": _version("transformers"),
            "accelerate": _version("accelerate"),
            "safetensors": _version("safetensors"),
            "imageio": _version("imageio"),
            "imageio_ffmpeg": _version("imageio_ffmpeg"),
            "huggingface_hub": _version("huggingface_hub"),
            "psutil": _version("psutil"),
            "sentencepiece": _version("sentencepiece"),
            "tiktoken": _version("tiktoken"),
            "google.protobuf": _version("google.protobuf"),
        },
    }


def _base_result(args: argparse.Namespace, result_path: Path) -> dict[str, Any]:
    env_keys = [
        "HF_HUB_OFFLINE",
        "TRANSFORMERS_OFFLINE",
        "PYTORCH_ENABLE_MPS_FALLBACK",
        "PYTORCH_MPS_HIGH_WATERMARK_RATIO",
        "PYTORCH_MPS_LOW_WATERMARK_RATIO",
        "HF_HOME",
        "HF_HUB_CACHE",
    ]
    fallback = os.getenv("PYTORCH_ENABLE_MPS_FALLBACK") == "1"
    return {
        "contract": "modelforge.wan21.phase0.v1",
        "scenario": args.scenario,
        "status": "started",
        "started_at": _now_iso(),
        "ended_at": None,
        "result_path": str(result_path),
        "command": _sanitize_argv(sys.argv),
        "environment": {key: os.getenv(key) for key in env_keys if os.getenv(key) is not None},
        "fallback_enabled": fallback,
        "dangerous_mps_high_watermark_disabled": os.getenv("PYTORCH_MPS_HIGH_WATERMARK_RATIO") == "0.0",
        "snapshot": str(Path(args.snapshot).expanduser().resolve()),
        "model": {"id": MODEL_ID, "revision": args.revision},
        "workload": {
            "prompt_hash": _sha256_text(args.prompt),
            "frames": args.frames,
            "fps": args.fps,
            "height": args.height,
            "width": args.width,
            "steps": args.steps,
            "seed": args.seed,
            "dtype": "bfloat16",
            "vae_dtype": "float32",
            "vae_slicing": True,
            "vae_tiling": True,
            "guidance_scale": args.guidance_scale,
            "placement": args.placement,
            "cancel_at_progress": args.cancel_at if args.scenario == "cancel" else None,
        },
        "offline_required": True,
        "timings": [],
        "runs": [],
        "memory_samples": [],
        "memory_peaks": {},
        "errors": [],
        **_host_and_packages(),
    }


class ScenarioRecorder:
    def __init__(self, result: dict[str, Any], result_path: Path, sampler: MemorySampler) -> None:
        self.result = result
        self.result_path = result_path
        self.sampler = sampler

    def write(self, status: str | None = None) -> None:
        if status is not None:
            self.result["status"] = status
        samples = self.sampler.snapshot()
        self.result["memory_samples"] = samples
        self.result["memory_peaks"] = _peaks(samples)
        _atomic_write_json(self.result_path, self.result)

    def boundary(self, label: str, status: str | None = None) -> None:
        self.sampler.boundary(label)
        self.write(status=status)


def _start_timing(result: dict[str, Any], name: str) -> Timing:
    timing = Timing(name=name, started_at=_now_iso(), start_perf_s=time.perf_counter())
    result["timings"].append(timing.to_json())
    return timing


def _finish_timing(result: dict[str, Any], timing: Timing) -> None:
    timing.finish()
    for index in range(len(result["timings"]) - 1, -1, -1):
        if result["timings"][index]["name"] == timing.name and result["timings"][index]["end_perf_s"] is None:
            result["timings"][index] = timing.to_json()
            return
    result["timings"].append(timing.to_json())


def _load_pipeline_cpu(args: argparse.Namespace, torch_module: Any, recorder: ScenarioRecorder) -> Any:
    from diffusers import AutoencoderKLWan, WanPipeline

    snapshot = Path(args.snapshot).expanduser().resolve()
    timing = _start_timing(recorder.result, "load_pipeline_cpu")
    recorder.boundary("before_load_pipeline_cpu")
    vae = AutoencoderKLWan.from_pretrained(
        str(snapshot),
        subfolder="vae",
        torch_dtype=torch_module.float32,
        local_files_only=True,
    )
    pipe = WanPipeline.from_pretrained(
        str(snapshot),
        vae=vae,
        torch_dtype=torch_module.bfloat16,
        local_files_only=True,
    )
    _finish_timing(recorder.result, timing)
    recorder.boundary("after_load_pipeline_cpu")

    timing = _start_timing(recorder.result, "configure_pipeline_placement")
    if args.placement == "resident-mps":
        pipe = pipe.to("mps")
    else:
        pipe.enable_model_cpu_offload(device="mps")
    _finish_timing(recorder.result, timing)
    recorder.boundary("after_configure_pipeline_placement")

    pipe.vae.enable_slicing()
    pipe.vae.enable_tiling()
    recorder.result["pipeline"] = {
        "class": type(pipe).__name__,
        "components": sorted(pipe.components.keys()),
        "device": "mps",
        "placement": args.placement,
        "dtype": "bfloat16",
        "vae_dtype": "float32",
        "vae_slicing": True,
        "vae_tiling": True,
    }
    recorder.write("pipeline_loaded")
    return pipe


def _check_raw_frames(frames: Any) -> dict[str, Any]:
    import numpy as np

    arrays = [np.asarray(frame) for frame in frames]
    finite = True
    variances: list[float] = []
    means: list[float] = []
    for array in arrays:
        if not np.isfinite(array.astype("float32")).all():
            finite = False
        variances.append(float(np.var(array)))
        means.append(float(np.mean(array)))
    return {
        "frame_count": len(arrays),
        "finite": finite,
        "min_variance": min(variances) if variances else None,
        "max_variance": max(variances) if variances else None,
        "mean_luma_min": min(means) if means else None,
        "mean_luma_max": max(means) if means else None,
        "all_zero_or_black": bool(arrays) and all(float(np.max(array)) <= 1.0 for array in arrays),
    }


def _validate_mp4(path: Path, *, expected_width: int, expected_height: int, expected_frames: int, expected_fps: int) -> dict[str, Any]:
    import imageio.v2 as imageio
    import numpy as np

    validation: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "non_empty": path.exists() and path.stat().st_size > 0,
        "ok": False,
        "errors": [],
        "warnings": [],
    }
    if not validation["exists"] or not validation["non_empty"]:
        validation["errors"].append("missing_or_empty")
        return validation

    validation["bytes"] = path.stat().st_size
    validation["sha256"] = _sha256_file(path)
    try:
        reader = imageio.get_reader(str(path), "ffmpeg")
        meta = reader.get_meta_data()
        validation["metadata"] = {key: _jsonable(value) for key, value in meta.items()}
        size = meta.get("size")
        fps = meta.get("fps")
        if list(size or []) != [expected_width, expected_height]:
            validation["errors"].append(f"resolution {size} != [{expected_width}, {expected_height}]")
        if fps is None or abs(float(fps) - float(expected_fps)) > 0.5:
            validation["errors"].append(f"fps {fps} not approximately {expected_fps}")

        decoded = 0
        sampled_indices = {0, max(0, expected_frames // 2), max(0, expected_frames - 1)}
        sampled: list[dict[str, Any]] = []
        for index, frame in enumerate(reader):
            decoded += 1
            if index in sampled_indices:
                arr = np.asarray(frame)
                arr_float = arr.astype("float32")
                sampled.append(
                    {
                        "index": index,
                        "shape": list(arr.shape),
                        "finite": bool(np.isfinite(arr_float).all()),
                        "variance": float(np.var(arr_float)),
                        "mean": float(np.mean(arr_float)),
                        "max": float(np.max(arr_float)),
                    }
                )
        reader.close()
        validation["decoded_frames"] = decoded
        validation["sampled_frames"] = sampled
        if decoded != expected_frames:
            validation["warnings"].append(f"decoded frame count {decoded} != target {expected_frames}; encoder metadata may differ")
        if abs(decoded - expected_frames) > 1:
            validation["errors"].append(f"decoded frame count {decoded} too far from target {expected_frames}")
        if any(not item["finite"] for item in sampled):
            validation["errors"].append("nan_or_inf_in_sampled_frame")
        if sampled and all(item["max"] <= 1.0 or item["variance"] <= 1e-6 for item in sampled):
            validation["errors"].append("sampled_frames_black_or_zero_variance")
    except Exception as exc:
        validation["errors"].append(f"container_parse_or_decode_failed: {exc}")
    validation["ok"] = not validation["errors"]
    return validation


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return str(value)
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return str(value)


def _generate_once(
    args: argparse.Namespace,
    pipe: Any,
    torch_module: Any,
    recorder: ScenarioRecorder,
    *,
    run_label: str,
    cancel_at: float | None = None,
) -> dict[str, Any]:
    from diffusers.utils import export_to_video

    output_dir = Path(args.output).resolve() / "videos"
    output_dir.mkdir(parents=True, exist_ok=True)
    final_path = output_dir / f"{args.scenario}_{run_label}.mp4"
    tmp_path = output_dir / f".{args.scenario}_{run_label}.tmp.mp4"
    for candidate in (final_path, tmp_path):
        if candidate.exists():
            candidate.unlink()

    run: dict[str, Any] = {
        "label": run_label,
        "status": "started",
        "started_at": _now_iso(),
        "seed": args.seed,
        "progress_events": [],
        "memory_before": recorder.sampler.boundary(f"{run_label}_before_generate"),
    }
    recorder.result["runs"].append(run)
    recorder.write("running")

    cancel_requested_perf: float | None = None
    cancel_requested_at: str | None = None

    def callback(_pipe: Any, step_index: int, timestep: Any, callback_kwargs: dict[str, Any]) -> dict[str, Any]:
        nonlocal cancel_requested_perf, cancel_requested_at
        total = max(args.steps, 1)
        progress = float(step_index + 1) / float(total)
        event = {
            "step": int(step_index + 1),
            "total": total,
            "progress": round(progress, 4),
            "timestep": str(timestep),
            "timestamp": _now_iso(),
        }
        run["progress_events"].append(event)
        if (step_index + 1) == 1 or (step_index + 1) % 5 == 0:
            recorder.sampler.boundary(f"{run_label}_step_{step_index + 1}")
            recorder.write("running")
        if cancel_at is not None and progress >= cancel_at:
            cancel_requested_perf = time.perf_counter()
            cancel_requested_at = _now_iso()
            run["cancel_requested_at"] = cancel_requested_at
            run["cancel_requested_progress"] = round(progress, 4)
            recorder.sampler.boundary(f"{run_label}_cancel_requested")
            recorder.write("cancelling")
            raise ScenarioCancelled(f"requested cancellation at progress {progress:.4f}")
        return callback_kwargs

    timing = Timing(name=f"{run_label}_generate", started_at=_now_iso(), start_perf_s=time.perf_counter())
    run["timings"] = [timing.to_json()]
    try:
        generator = torch_module.Generator(device="mps").manual_seed(args.seed)
        frames = pipe(
            prompt=args.prompt,
            num_videos_per_prompt=1,
            num_inference_steps=args.steps,
            num_frames=args.frames,
            height=args.height,
            width=args.width,
            guidance_scale=args.guidance_scale,
            generator=generator,
            callback_on_step_end=callback,
        ).frames[0]
        timing.finish()
        run["timings"][0] = timing.to_json()
        run["memory_after_generate"] = recorder.sampler.boundary(f"{run_label}_after_generate")
        run["raw_frame_check"] = _check_raw_frames(frames)
        recorder.write("running")

        export_timing = Timing(name=f"{run_label}_export", started_at=_now_iso(), start_perf_s=time.perf_counter())
        run["timings"].append(export_timing.to_json())
        export_to_video(frames, str(tmp_path), fps=args.fps)
        export_timing.finish()
        run["timings"][-1] = export_timing.to_json()

        validation = _validate_mp4(
            tmp_path,
            expected_width=args.width,
            expected_height=args.height,
            expected_frames=args.frames,
            expected_fps=args.fps,
        )
        run["mp4_validation"] = validation
        if validation["ok"]:
            os.replace(tmp_path, final_path)
            run["output_path"] = str(final_path)
            run["output_bytes"] = final_path.stat().st_size
            run["output_sha256"] = _sha256_file(final_path)
            run["status"] = "success"
        else:
            tmp_path.unlink(missing_ok=True)
            run["status"] = "failed"
            run["error"] = {"categories": ["output_validation"], "message": "; ".join(validation["errors"])}
        del frames
    except ScenarioCancelled as exc:
        timing.finish()
        run["timings"][0] = timing.to_json()
        aborted_perf = time.perf_counter()
        run["status"] = "cancelled"
        run["cancel_error"] = str(exc)
        run["cancel_aborted_at"] = _now_iso()
        run["cancel_latency_s"] = round(aborted_perf - cancel_requested_perf, 6) if cancel_requested_perf is not None else None
        run["cancel_requested_at"] = cancel_requested_at
        tmp_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        run["no_usable_mp4_published"] = not final_path.exists()
    except BaseException as exc:
        timing.finish()
        run["timings"][0] = timing.to_json()
        run["status"] = "failed"
        run["error"] = _classify_error(exc)
        tmp_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        raise
    finally:
        run["memory_after_run"] = recorder.sampler.boundary(f"{run_label}_after_run")
        run["ended_at"] = _now_iso()
        recorder.write("running")
    return run


def _cleanup_pipeline(pipe_holder: list[Any], torch_module: Any, recorder: ScenarioRecorder) -> None:
    timing = _start_timing(recorder.result, "cleanup")
    pipe_holder[0] = None
    gc.collect()
    if hasattr(torch_module, "mps"):
        torch_module.mps.empty_cache()
    _finish_timing(recorder.result, timing)
    recorder.boundary("after_cleanup")


def _memory_growth_summary(result: dict[str, Any]) -> dict[str, Any]:
    per_run: list[dict[str, Any]] = []
    for run in result.get("runs", []):
        mps = ((run.get("memory_after_run") or {}).get("mps") or {}) if isinstance(run, dict) else {}
        per_run.append(
            {
                "label": run.get("label"),
                "status": run.get("status"),
                "rss_bytes": (run.get("memory_after_run") or {}).get("rss_bytes"),
                "mps_current_allocated_memory": mps.get("current_allocated_memory"),
                "mps_driver_allocated_memory": mps.get("driver_allocated_memory"),
            }
        )
    driver_values = [item["mps_driver_allocated_memory"] for item in per_run if isinstance(item.get("mps_driver_allocated_memory"), int)]
    rss_values = [item["rss_bytes"] for item in per_run if isinstance(item.get("rss_bytes"), int)]
    return {
        "per_run": per_run,
        "driver_growth_bytes": driver_values[-1] - driver_values[0] if len(driver_values) >= 2 else None,
        "rss_growth_bytes": rss_values[-1] - rss_values[0] if len(rss_values) >= 2 else None,
        "strictly_increasing_driver": all(a < b for a, b in zip(driver_values, driver_values[1:])) if len(driver_values) >= 2 else None,
    }


def run_scenario(args: argparse.Namespace) -> Path:
    import torch

    if not Path(args.snapshot).expanduser().resolve().exists():
        raise SystemExit(f"snapshot does not exist: {args.snapshot}")

    scenario_stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    result_path = Path(args.output).resolve() / "results" / f"phase0_{args.scenario}_{scenario_stamp}.json"
    sampler = MemorySampler(torch, interval_s=args.sample_interval)
    result = _base_result(args, result_path)
    result["torch_mps"] = {
        "is_built": bool(torch.backends.mps.is_built()),
        "is_available": bool(torch.backends.mps.is_available()),
    }
    recorder = ScenarioRecorder(result, result_path, sampler)
    sampler.start()
    recorder.write("started")

    pipe = None
    try:
        if not result["torch_mps"]["is_available"]:
            result["errors"].append({"categories": ["mps_unavailable"], "message": "torch.backends.mps.is_available() is false"})
            recorder.write("failed")
            return result_path

        pipe = _load_pipeline_cpu(args, torch, recorder)
        if args.scenario == "load-only":
            recorder.write("success")
            return result_path

        if args.scenario == "first":
            _generate_once(args, pipe, torch, recorder, run_label="first")
        elif args.scenario == "warm-repeat":
            _generate_once(args, pipe, torch, recorder, run_label="warm_1")
            _generate_once(args, pipe, torch, recorder, run_label="warm_2")
        elif args.scenario == "cancel":
            _generate_once(args, pipe, torch, recorder, run_label="cancel_25pct", cancel_at=args.cancel_at)
        elif args.scenario == "repeat-three":
            for index in range(3):
                _generate_once(args, pipe, torch, recorder, run_label=f"repeat_{index + 1}")
            result["memory_growth"] = _memory_growth_summary(result)
        else:
            raise AssertionError(args.scenario)

        failed_runs = [run for run in result["runs"] if run.get("status") == "failed"]
        if failed_runs:
            recorder.write("failed")
        else:
            recorder.write("success")
    except KeyboardInterrupt as exc:
        result["errors"].append(_classify_error(exc))
        recorder.write("interrupted")
        raise
    except BaseException as exc:
        result["errors"].append(_classify_error(exc))
        recorder.write("failed")
        return result_path
    finally:
        if pipe is not None:
            pipeline_to_cleanup = [pipe]
            pipe = None
            _cleanup_pipeline(pipeline_to_cleanup, torch, recorder)
        sampler.stop()
        result["ended_at"] = _now_iso()
        if result.get("status") in {"started", "running", "pipeline_loaded"}:
            result["status"] = "failed"
        result["memory_samples"] = sampler.snapshot()
        result["memory_peaks"] = _peaks(result["memory_samples"])
        _atomic_write_json(result_path, result)
    return result_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one Wan2.1 T2V 1.3B Phase 0 MPS benchmark scenario.")
    parser.add_argument(
        "--scenario",
        required=True,
        choices=("load-only", "first", "warm-repeat", "cancel", "repeat-three"),
        help="Run exactly one benchmark scenario.",
    )
    parser.add_argument("--snapshot", default=DEFAULT_SNAPSHOT)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--revision", default=REVISION)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--frames", type=int, default=DEFAULT_FRAMES)
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--steps", type=int, default=DEFAULT_STEPS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--guidance-scale", type=float, default=DEFAULT_GUIDANCE_SCALE)
    parser.add_argument(
        "--placement",
        choices=("model-cpu-offload", "resident-mps"),
        default="model-cpu-offload",
        help="Use component-level MPS offload by default; resident-mps is a diagnostic high-memory mode.",
    )
    parser.add_argument("--cancel-at", type=float, default=0.25)
    parser.add_argument("--sample-interval", type=float, default=1.0)
    args = parser.parse_args()
    if args.sample_interval <= 0:
        parser.error("--sample-interval must be positive")
    if not 0 < args.cancel_at < 1:
        parser.error("--cancel-at must be between 0 and 1")
    if args.revision != REVISION:
        parser.error(f"Phase 0 is pinned to revision {REVISION}")
    return args


def main() -> int:
    args = parse_args()
    result_path = run_scenario(args)
    print(json.dumps({"result": str(result_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
