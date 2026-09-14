"""Source-neutral model discovery and repository metadata.

The desktop model center should not render raw Hugging Face objects. This
module normalises repository search results, repository files and compatibility
signals into a small internal contract that can later be backed by more model
sources.
"""

from __future__ import annotations

import importlib.util
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from core.config import settings

TASK_LABELS = {
    "all": "全部",
    "text-generation": "文本生成",
    "embedding": "Embedding",
    "vision": "视觉",
    "speech": "语音",
    "video": "视频",
    "multimodal": "多模态",
    "other": "其他",
}

_TEXT_PIPELINES = {
    "text-generation",
    "text2text-generation",
    "conversational",
    "question-answering",
    "summarization",
    "translation",
}
_EMBEDDING_PIPELINES = {"feature-extraction", "sentence-similarity"}
_VISION_PIPELINES = {
    "image-classification",
    "object-detection",
    "image-segmentation",
    "zero-shot-image-classification",
    "image-to-text",
}
_SPEECH_PIPELINES = {
    "automatic-speech-recognition",
    "audio-classification",
    "text-to-speech",
    "audio-to-audio",
}
_VIDEO_PIPELINES = {"text-to-video", "image-to-video", "video-classification"}
_MULTIMODAL_PIPELINES = {
    "visual-question-answering",
    "document-question-answering",
    "image-text-to-text",
    "any-to-any",
}

_SUPPORT_FILE_NAMES = {
    "config.json",
    "generation_config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "vocab.json",
    "vocab.txt",
    "merges.txt",
    "sentencepiece.bpe.model",
    "spiece.model",
    "preprocessor_config.json",
    "processor_config.json",
    "feature_extractor_config.json",
    "image_processor_config.json",
    "model_index.json",
    "scheduler_config.json",
    "README.md",
}
_WEIGHT_SUFFIXES = {".gguf", ".ggml", ".safetensors", ".bin", ".pt", ".pth", ".onnx", ".ckpt"}
_QUANT_RE = re.compile(r"(?i)(?:^|[-_.])(Q\d(?:_[A-Z0-9]+){0,2}|IQ\d_[A-Z0-9]+|F16|BF16|FP16|FP32)(?:[-_.]|$)")
_PARAM_RE = re.compile(r"(?i)(\d+(?:\.\d+)?)\s*([bm])\b")


@dataclass(frozen=True)
class CatalogQuery:
    query: str = ""
    category: str = "all"
    model_format: str | None = None
    library: str | None = None
    author: str | None = None
    gated: bool | None = None
    compatible: bool | None = None
    sort: str = "relevance"
    limit: int = 30


def parse_hf_repo_id(value: str) -> str:
    """Accept a repo id or Hugging Face model URL and return ``owner/name``."""
    raw = (value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme and parsed.netloc:
        host = parsed.netloc.lower()
        parts = [part for part in parsed.path.split("/") if part]
        if "huggingface.co" in host and len(parts) >= 2:
            if parts[0] in {"models", "spaces", "datasets"} and len(parts) >= 3:
                return "/".join(parts[1:3])
            return "/".join(parts[:2])
    return raw.strip("/")


class HuggingFaceCatalogAdapter:
    source_id = "huggingface"
    source_label = "Hugging Face"

    def __init__(self, endpoint: str | None = None):
        self.endpoint = (endpoint or settings.hf_endpoint or "").strip().rstrip("/") or None

    def _api(self):
        from huggingface_hub import HfApi

        return HfApi(endpoint=self.endpoint) if self.endpoint else HfApi()

    def search(self, query: CatalogQuery) -> list[dict]:
        api = self._api()
        repo_query = parse_hf_repo_id(query.query)
        kwargs: dict[str, Any] = {"limit": max(1, min(query.limit, 100)), "full": False}
        if repo_query:
            kwargs["search"] = repo_query
        if query.author:
            kwargs["author"] = query.author
        sort = _hf_sort(query.sort)
        if sort:
            kwargs.update(sort)
        items = [self._normalise_summary(item) for item in api.list_models(**kwargs)]
        return _apply_catalog_filters(items, query)

    def detail(self, repo_id_or_url: str) -> dict:
        repo_id = parse_hf_repo_id(repo_id_or_url)
        info = self._api().model_info(repo_id, files_metadata=True)
        summary = self._normalise_summary(info)
        files = [_normalise_file(sibling) for sibling in getattr(info, "siblings", []) or []]
        formats = _infer_formats(summary["tags"], summary.get("library"), files)
        category = _infer_category(summary.get("pipeline_tag"), summary["tags"], summary.get("library"), formats)
        params = _infer_parameters(summary["repo_id"], summary["tags"], getattr(info, "config", None))
        compatibility = _compatibility(category, formats, summary.get("library"))
        selected = _recommended_files(category, formats, files)
        size = sum(int(item.get("size_bytes") or 0) for item in files)
        readme = _readme_excerpt(repo_id, self.endpoint)
        return {
            **summary,
            "repo_id": repo_id,
            "task_category": category,
            "task_label": TASK_LABELS.get(category, "其他"),
            "formats": formats,
            "parameters": params,
            "compatibility": compatibility,
            "files": files,
            "recommended_files": selected,
            "total_size_bytes": size,
            "total_size": _format_bytes(size),
            "readme": readme or summary.get("description") or "该仓库未提供可预览的 README。",
            "license": _license_from_tags(summary["tags"]),
            "download_path": str(Path(settings.model_dir) / repo_id.replace("/", "_")),
            "disk_free_bytes": _disk_free_bytes(settings.model_dir),
            "disk_free": _format_bytes(_disk_free_bytes(settings.model_dir)),
            "gated": _is_gated(getattr(info, "gated", None), summary["tags"]),
            "private": bool(getattr(info, "private", False)),
        }

    def _normalise_summary(self, model: Any) -> dict:
        tags = [str(tag) for tag in (getattr(model, "tags", None) or []) if str(tag)]
        repo_id = str(getattr(model, "modelId", None) or getattr(model, "id", ""))
        library = getattr(model, "library_name", None) or _library_from_tags(tags)
        pipeline = getattr(model, "pipeline_tag", None) or _pipeline_from_tags(tags)
        formats = _infer_formats(tags, library, [])
        category = _infer_category(pipeline, tags, library, formats)
        compatibility = _compatibility(category, formats, library)
        return {
            "source": self.source_id,
            "source_label": self.source_label,
            "repo_id": repo_id,
            "name": repo_id.split("/")[-1] if repo_id else "",
            "author": str(getattr(model, "author", None) or (repo_id.split("/")[0] if "/" in repo_id else "")),
            "pipeline_tag": pipeline or "",
            "task_category": category,
            "task_label": TASK_LABELS.get(category, "其他"),
            "library": library or "",
            "formats": formats,
            "parameters": _infer_parameters(repo_id, tags, getattr(model, "config", None)),
            "downloads": int(getattr(model, "downloads", 0) or 0),
            "likes": int(getattr(model, "likes", 0) or 0),
            "updated_at": _iso(getattr(model, "lastModified", None) or getattr(model, "last_modified", None)),
            "tags": tags[:16],
            "description": _description(model),
            "gated": _is_gated(getattr(model, "gated", None), tags),
            "private": bool(getattr(model, "private", False)),
            "compatibility": compatibility,
        }


class ModelCatalogService:
    """Facade for source-neutral model discovery."""

    def __init__(self, adapters: list[HuggingFaceCatalogAdapter] | None = None):
        self.adapters = adapters or [HuggingFaceCatalogAdapter()]

    def search(self, query: CatalogQuery) -> list[dict]:
        results: list[dict] = []
        for adapter in self.adapters:
            results.extend(adapter.search(query))
        return _apply_catalog_filters(results, query)[: max(1, min(query.limit, 100))]

    def detail(self, repo_id_or_url: str, source: str = "huggingface") -> dict:
        for adapter in self.adapters:
            if adapter.source_id == source:
                return adapter.detail(repo_id_or_url)
        raise ValueError(f"unknown model source: {source}")


def _hf_sort(sort: str) -> dict[str, Any]:
    mapping = {
        "popular": {"sort": "likes", "direction": -1},
        "downloads": {"sort": "downloads", "direction": -1},
        "updated": {"sort": "lastModified", "direction": -1},
    }
    return mapping.get((sort or "").lower(), {})


def _apply_catalog_filters(items: list[dict], query: CatalogQuery) -> list[dict]:
    filtered = items
    if query.category and query.category != "all":
        filtered = [item for item in filtered if item.get("task_category") == query.category]
    if query.model_format:
        wanted = query.model_format.lower()
        filtered = [item for item in filtered if wanted in [fmt.lower() for fmt in item.get("formats", [])]]
    if query.library:
        wanted = query.library.lower()
        filtered = [item for item in filtered if wanted in str(item.get("library") or "").lower()]
    if query.gated is not None:
        filtered = [item for item in filtered if bool(item.get("gated")) is query.gated]
    if query.compatible is not None:
        filtered = [item for item in filtered if bool((item.get("compatibility") or {}).get("runnable")) is query.compatible]
    return filtered


def _normalise_file(sibling: Any) -> dict:
    path = str(getattr(sibling, "rfilename", None) or getattr(sibling, "filename", ""))
    lfs = getattr(sibling, "lfs", None)
    size = _as_int(getattr(sibling, "size", None))
    file_format = _file_format(path)
    role = _file_role(path, file_format, size)
    quant = _quant_from_name(path)
    return {
        "path": path,
        "name": PurePosixPath(path).name,
        "format": file_format,
        "role": role,
        "quantization": quant,
        "size_bytes": size,
        "size": _format_bytes(size),
        "sha256": str(getattr(lfs, "sha256", "") or ""),
        "recommended": False,
    }


def _infer_formats(tags: list[str], library: str | None, files: list[dict]) -> list[str]:
    values: list[str] = []
    lower_tags = {tag.lower() for tag in tags}
    file_formats = {str(item.get("format") or "").lower() for item in files}
    if "gguf" in lower_tags or "gguf" in file_formats:
        values.append("GGUF")
    if "safetensors" in lower_tags or "safetensors" in file_formats:
        values.append("SafeTensors")
    if file_formats.intersection({"pytorch", "bin", "pt", "pth"}) or "pytorch" in lower_tags:
        values.append("PyTorch")
    if "onnx" in lower_tags or "onnx" in file_formats:
        values.append("ONNX")
    lib = (library or "").lower()
    if lib == "diffusers" or "diffusers" in lower_tags or any(item.get("name") == "model_index.json" for item in files):
        values.append("Diffusers")
    if lib in {"transformers", "sentence-transformers"} or "transformers" in lower_tags or any(item.get("name") == "config.json" for item in files):
        values.append("Transformers")
    return _dedupe(values or ([library.title()] if library else ["Transformers"]))


def _infer_category(pipeline: str | None, tags: list[str], library: str | None, formats: list[str]) -> str:
    value = (pipeline or "").lower()
    lower_tags = {tag.lower() for tag in tags}
    lib = (library or "").lower()
    if value in _TEXT_PIPELINES or "text-generation" in lower_tags or "gguf" in [fmt.lower() for fmt in formats]:
        return "text-generation"
    if value in _EMBEDDING_PIPELINES or lib == "sentence-transformers" or "sentence-transformers" in lower_tags:
        return "embedding"
    if value in _VISION_PIPELINES or any(tag.startswith("vision") for tag in lower_tags):
        return "vision"
    if value in _SPEECH_PIPELINES or any(tag.startswith("audio") or "whisper" in tag for tag in lower_tags):
        return "speech"
    if value in _VIDEO_PIPELINES or any("video" in tag for tag in lower_tags):
        return "video"
    if value in _MULTIMODAL_PIPELINES or any(tag in {"multimodal", "vision-language"} for tag in lower_tags):
        return "multimodal"
    return "other"


def _compatibility(category: str, formats: list[str], library: str | None) -> dict:
    lower_formats = {fmt.lower() for fmt in formats}
    reasons: list[str] = []
    runtimes: list[str] = []
    if "gguf" in lower_formats:
        runtimes.append("llama_cpp")
        if not _module_available("llama_cpp"):
            reasons.append("未安装 llama-cpp-python，下载后暂不能在当前后端运行。")
    if category in {"text-generation", "embedding"} and lower_formats.intersection({"transformers", "safetensors", "pytorch"}):
        runtimes.append("transformers")
        if not _module_available("transformers"):
            reasons.append("未安装 transformers，下载后暂不能在当前后端运行。")
    if category in {"vision", "speech", "video", "multimodal"}:
        reasons.append("当前运行后端尚未提供该任务类型的本地运行入口，可下载后作为模型资产管理。")
    if "onnx" in lower_formats and not runtimes:
        reasons.append("当前后端尚未接入 ONNX Runtime。")
    if (library or "").lower() == "diffusers":
        reasons.append("当前后端尚未接入 Diffusers 推理运行时。")
    runnable = bool(runtimes) and not reasons
    return {
        "downloadable": True,
        "runnable": runnable,
        "status": "supported" if runnable else ("partial" if runtimes else "download_only"),
        "runtimes": _dedupe(runtimes),
        "reason": "；".join(_dedupe(reasons)) if reasons else "当前后端可运行。",
    }


def _recommended_files(category: str, formats: list[str], files: list[dict]) -> list[str]:
    for item in files:
        item["recommended"] = False
    gguf = [item for item in files if item.get("format") == "gguf"]
    if gguf:
        preferred = [item for item in gguf if item.get("quantization") in {"Q4_K_M", "Q5_K_M", "Q8_0"}]
        chosen = preferred[:2] or sorted(gguf, key=lambda item: int(item.get("size_bytes") or 0))[:1]
        for item in chosen:
            item["recommended"] = True
        return [item["path"] for item in chosen]

    support = [item for item in files if item.get("role") in {"config", "tokenizer", "processor", "readme"}]
    weights = [item for item in files if item.get("role") == "weight"]
    safetensors = [item for item in weights if item.get("format") == "safetensors"]
    pytorch = [item for item in weights if item.get("format") in {"pytorch", "bin", "pt", "pth"}]
    onnx = [item for item in weights if item.get("format") == "onnx"]
    primary = safetensors or pytorch or onnx
    if primary:
        # Keep sharded sets together, but avoid selecting every unrelated weight
        # variant in a repository.
        index_names = {"model.safetensors.index.json", "pytorch_model.bin.index.json"}
        indexed = [item for item in files if item.get("name") in index_names]
        chosen = primary if len(primary) <= 8 else primary[:1]
        chosen = _dedupe_objects(indexed + support + chosen)
    else:
        chosen = support
    for item in chosen:
        item["recommended"] = True
    return [item["path"] for item in chosen]


def _file_format(path: str) -> str:
    lower = path.lower()
    name = PurePosixPath(lower).name
    suffix = PurePosixPath(lower).suffix
    if suffix in {".gguf", ".ggml"}:
        return "gguf"
    if suffix == ".safetensors":
        return "safetensors"
    if name.endswith("pytorch_model.bin") or suffix == ".bin":
        return "pytorch"
    if suffix in {".pt", ".pth", ".ckpt"}:
        return suffix.strip(".")
    if suffix == ".onnx":
        return "onnx"
    if name == "model_index.json":
        return "diffusers"
    if suffix == ".json":
        return "json"
    if suffix == ".md":
        return "markdown"
    return suffix.strip(".") or "unknown"


def _file_role(path: str, file_format: str, size: int) -> str:
    name = PurePosixPath(path).name
    if file_format in {"gguf", "ggml", "safetensors", "pytorch", "pt", "pth", "onnx", "ckpt"}:
        return "weight"
    if name == "README.md":
        return "readme"
    if name in _SUPPORT_FILE_NAMES:
        if "tokenizer" in name or name in {"vocab.json", "vocab.txt", "merges.txt", "spiece.model"}:
            return "tokenizer"
        if "processor" in name or "extractor" in name or "preprocessor" in name:
            return "processor"
        return "config"
    if size and size > 100 * 1024 * 1024 and Path(name).suffix.lower() in _WEIGHT_SUFFIXES:
        return "weight"
    return "other"


def _quant_from_name(path: str) -> str:
    match = _QUANT_RE.search(PurePosixPath(path).name)
    return match.group(1).upper() if match else ""


def _infer_parameters(repo_id: str, tags: list[str], config: Any) -> str:
    for value in [repo_id, *tags]:
        match = _PARAM_RE.search(str(value).replace("-", " "))
        if match:
            return f"{match.group(1)}{match.group(2).upper()}"
    if isinstance(config, dict):
        for key in ("num_parameters", "model_size"):
            value = config.get(key)
            if isinstance(value, (int, float)) and value > 0:
                return _format_params(float(value))
            if isinstance(value, str):
                return value
    return "未知"


def _format_params(value: float) -> str:
    return f"{value / 1_000_000_000:.1f}B" if value >= 1_000_000_000 else f"{value / 1_000_000:.0f}M"


def _readme_excerpt(repo_id: str, endpoint: str | None) -> str:
    try:
        from huggingface_hub import hf_hub_download

        kwargs = {"repo_id": repo_id, "filename": "README.md"}
        if endpoint:
            kwargs["endpoint"] = endpoint
        path = hf_hub_download(**kwargs)
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    return text[:6000]


def _library_from_tags(tags: list[str]) -> str:
    for tag in tags:
        lower = tag.lower()
        if lower.startswith("library:"):
            return tag.split(":", 1)[1]
        if lower in {"transformers", "diffusers", "sentence-transformers", "onnx"}:
            return lower
    return ""


def _pipeline_from_tags(tags: list[str]) -> str:
    for tag in tags:
        lower = tag.lower()
        if lower.startswith("pipeline_tag:"):
            return tag.split(":", 1)[1]
    return ""


def _description(model: Any) -> str:
    card = getattr(model, "cardData", None) or getattr(model, "card_data", None)
    if isinstance(card, dict):
        for key in ("summary", "description"):
            value = card.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:300]
    return ""


def _license_from_tags(tags: list[str]) -> str:
    for tag in tags:
        lower = tag.lower()
        if lower.startswith("license:"):
            return tag.split(":", 1)[1]
    return "未声明"


def _is_gated(value: Any, tags: list[str]) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() not in {"", "false", "none", "public"}
    lower_tags = {tag.lower() for tag in tags}
    return "gated" in lower_tags or "private" in lower_tags


def _disk_free_bytes(path: str | os.PathLike[str]) -> int:
    try:
        target = Path(path)
        target.mkdir(mode=0o700, parents=True, exist_ok=True)
        return int(os.statvfs(target).f_bavail * os.statvfs(target).f_frsize)
    except OSError:
        return 0


def _format_bytes(value: int | None) -> str:
    amount = float(max(0, int(value or 0)))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{int(amount)} B" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TB"


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _iso(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _module_available(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _dedupe_objects(values: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for value in values:
        key = str(value.get("path") or "")
        if key and key not in seen:
            seen.add(key)
            result.append(value)
    return result


__all__ = ["CatalogQuery", "ModelCatalogService", "parse_hf_repo_id"]
