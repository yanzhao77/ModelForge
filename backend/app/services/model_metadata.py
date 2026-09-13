"""Best-effort, non-blocking model metadata detection.

The model registry records architecture / parameter / context information when
it is cheap to read, but a missing or unusual header must never block an
install or a download. Every function here therefore returns a (possibly empty)
dict and swallows I/O and parse errors instead of raising.

Two formats are supported:

* GGUF files: a bounded reader walks the key/value header without loading the
  tensor payload.
* Hugging Face directories: values are read from ``config.json``.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

#: Never read more than this many bytes of a GGUF header. Real headers are a few
#: kilobytes; the cap keeps a malformed file from turning install into a full
#: disk read.
_GGUF_HEADER_LIMIT = 8 * 1024 * 1024
_GGUF_MAX_KV = 4096

# GGUF value type ids -> fixed struct format (None means variable length).
_GGUF_SCALARS: dict[int, str] = {
    0: "<B",  # uint8
    1: "<b",  # int8
    2: "<H",  # uint16
    3: "<h",  # int16
    4: "<I",  # uint32
    5: "<i",  # int32
    6: "<f",  # float32
    7: "<?",  # bool
    8: None,  # string
    9: None,  # array
    10: "<Q",  # uint64
    11: "<q",  # int64
    12: "<d",  # float64
}


class _Reader:
    """Cursor over a bounded in-memory GGUF header buffer."""

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def take(self, count: int) -> bytes:
        if count < 0 or self.pos + count > len(self.data):
            raise ValueError("GGUF_HEADER_TRUNCATED")
        chunk = self.data[self.pos:self.pos + count]
        self.pos += count
        return chunk

    def unpack(self, fmt: str):
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self.take(size))[0]

    def string(self) -> str:
        length = self.unpack("<Q")
        return self.take(length).decode("utf-8", errors="replace")


def _skip_value(reader: _Reader, value_type: int) -> None:
    """Consume one GGUF value so the next key can be read."""
    fmt = _GGUF_SCALARS.get(value_type)
    if fmt is None and value_type == 8:
        reader.string()
        return
    if fmt is None and value_type == 9:
        element_type = reader.unpack("<I")
        count = reader.unpack("<Q")
        for _ in range(count):
            _skip_value(reader, element_type)
        return
    if fmt is None:
        raise ValueError(f"GGUF_UNKNOWN_VALUE_TYPE:{value_type}")
    reader.unpack(fmt)


def _read_value(reader: _Reader, value_type: int):
    """Read one GGUF value, returning a Python object for supported types."""
    if value_type == 8:
        return reader.string()
    if value_type == 9:
        element_type = reader.unpack("<I")
        count = reader.unpack("<Q")
        values = []
        for _ in range(min(count, 64)):
            values.append(_read_value(reader, element_type))
        for _ in range(max(0, count - 64)):
            _skip_value(reader, element_type)
        return values
    fmt = _GGUF_SCALARS.get(value_type)
    if fmt is None:
        raise ValueError(f"GGUF_UNKNOWN_VALUE_TYPE:{value_type}")
    return reader.unpack(fmt)


def read_gguf_metadata(path: str | Path) -> dict:
    """Extract a few human-meaningful fields from a GGUF header."""
    try:
        with open(path, "rb") as handle:
            header = handle.read(_GGUF_HEADER_LIMIT)
    except OSError:
        return {}
    if len(header) < 24 or header[:4] != b"GGUF":
        return {}
    try:
        reader = _Reader(header)
        reader.take(4)
        reader.unpack("<I")  # version
        reader.unpack("<Q")  # tensor_count
        kv_count = reader.unpack("<Q")
        if kv_count > _GGUF_MAX_KV:
            return {}
        raw: dict[str, object] = {}
        for _ in range(kv_count):
            key = reader.string()
            value_type = reader.unpack("<I")
            value = _read_value(reader, value_type)
            if isinstance(value, (str, int, float, bool)):
                raw[key] = value
    except (ValueError, struct.error, UnicodeDecodeError):
        return {}

    architecture = raw.get("general.architecture")
    metadata: dict[str, object] = {}
    if isinstance(architecture, str) and architecture:
        metadata["architecture"] = architecture
        context_length = raw.get(f"{architecture}.context_length")
        if isinstance(context_length, int) and context_length > 0:
            metadata["context_length"] = context_length
    name = raw.get("general.name")
    if isinstance(name, str) and name:
        metadata["family"] = name
    size_label = raw.get("general.size_label")
    if isinstance(size_label, str) and size_label:
        metadata["parameters"] = size_label
    file_type = raw.get("general.file_type")
    if isinstance(file_type, int):
        metadata["file_type"] = file_type
    return metadata


def read_transformers_metadata(path: str | Path) -> dict:
    """Extract architecture information from a Hugging Face model directory."""
    directory = Path(path)
    if not directory.is_dir():
        return {}
    try:
        payload = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    metadata: dict[str, object] = {}
    architectures = payload.get("architectures")
    if isinstance(architectures, list) and architectures:
        metadata["architecture"] = str(architectures[0])
    model_type = payload.get("model_type")
    if isinstance(model_type, str) and model_type:
        metadata.setdefault("family", model_type)
    context = payload.get("max_position_embeddings")
    if isinstance(context, int) and context > 0:
        metadata["context_length"] = context
    return metadata


def detect_metadata(path: str | None, *, model_format: str | None = None) -> dict:
    """Return whatever metadata can be read for this asset without raising."""
    if not path:
        return {}
    candidate = Path(str(path))
    suffix = candidate.suffix.lower()
    if suffix in {".gguf", ".ggml"}:
        return read_gguf_metadata(candidate)
    if candidate.is_dir():
        if any(candidate.glob("*.gguf")):
            for item in sorted(candidate.glob("*.gguf")):
                metadata = read_gguf_metadata(item)
                if metadata:
                    return metadata
            return {}
        return read_transformers_metadata(candidate)
    if (model_format or "").lower() in {"safetensors", "transformers"}:
        return read_transformers_metadata(candidate.parent)
    return {}


def directory_size_bytes(path: str | Path) -> int:
    """Total size of a model file or a model directory (0 when unknown)."""
    candidate = Path(str(path))
    try:
        if candidate.is_file():
            return int(candidate.stat().st_size)
        if candidate.is_dir():
            return int(
                sum(item.stat().st_size for item in candidate.rglob("*") if item.is_file())
            )
    except OSError:
        return 0
    return 0
