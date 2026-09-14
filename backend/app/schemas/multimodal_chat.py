"""Structured chat content contracts for multimodal turns."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TextSelection(BaseModel):
    kind: Literal["lines"]
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)

    @model_validator(mode="after")
    def _check_order(self):
        if self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self


class PageSelection(BaseModel):
    kind: Literal["pages"]
    pages: list[int] = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def _check_pages(self):
        if any(page < 1 for page in self.pages):
            raise ValueError("pages are 1-based")
        return self


class TimeSelection(BaseModel):
    kind: Literal["time"]
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)

    @model_validator(mode="after")
    def _check_order(self):
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class ImageRegionSelection(BaseModel):
    kind: Literal["region"]
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def _check_bounds(self):
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("image region must stay inside normalized bounds")
        return self


Selection = Annotated[
    TextSelection | PageSelection | TimeSelection | ImageRegionSelection,
    Field(discriminator="kind"),
]


class TextPart(BaseModel):
    type: Literal["text"]
    text: str = Field(min_length=1, max_length=200000)


class FilePart(BaseModel):
    type: Literal["file"]
    attachment_id: str = Field(min_length=1, max_length=64)
    selection: Selection | None = None
    processing: Literal["extract_text", "preview_only"] = "extract_text"


class ImagePart(BaseModel):
    type: Literal["image"]
    attachment_id: str = Field(min_length=1, max_length=64)
    detail: Literal["auto", "low", "high"] = "auto"
    selection: ImageRegionSelection | None = None


class AudioPart(BaseModel):
    type: Literal["audio"]
    attachment_id: str = Field(min_length=1, max_length=64)
    selection: TimeSelection | None = None
    processing: Literal["asr", "native", "preview_only"] = "asr"


class VideoPart(BaseModel):
    type: Literal["video"]
    attachment_id: str = Field(min_length=1, max_length=64)
    selection: TimeSelection | None = None
    processing: Literal["frames_asr", "native", "preview_only"] = "frames_asr"


ContentPart = Annotated[TextPart | FilePart | ImagePart | AudioPart | VideoPart, Field(discriminator="type")]


class StructuredMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user"] = "user"
    content: str = Field(default="", max_length=200000)
    parts: list[ContentPart] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _normalize_and_check(self):
        if self.content and not self.parts:
            self.parts = [TextPart(type="text", text=self.content)]
        if not self.content:
            self.content = text_projection(self.parts)
        if not self.content.strip() and not any(part.type in {"file", "image", "audio", "video"} for part in self.parts):
            raise ValueError("message requires text or at least one attachment part")
        return self


class ChatTarget(BaseModel):
    kind: Literal["legacy", "local", "remote"] = "legacy"
    model: str | None = Field(default=None, max_length=255)
    model_id: int | None = None
    runtime: str | None = Field(default=None, max_length=64)
    provider_id: int | None = None


class RequestedOutput(BaseModel):
    type: Literal["text", "artifact"] = "text"
    format: str | None = Field(default=None, max_length=32)


class TurnContextOptions(BaseModel):
    excluded_message_ids: list[int] = Field(default_factory=list, max_length=200)
    excluded_attachment_ids: list[str] = Field(default_factory=list, max_length=200)
    use_memory: bool = False


class ChatTurnCreate(BaseModel):
    schema_version: Literal[1] = 1
    session_id: int | None = None
    target: ChatTarget = Field(default_factory=ChatTarget)
    mode: Literal["chat", "agent"] = "chat"
    message: StructuredMessage
    requested_outputs: list[RequestedOutput] = Field(default_factory=lambda: [RequestedOutput(type="text")], max_length=10)
    context: TurnContextOptions = Field(default_factory=TurnContextOptions)
    idempotency_key: str = Field(min_length=8, max_length=160)


def part_dicts(parts: list[ContentPart]) -> list[dict]:
    return [part.model_dump(exclude_none=True) for part in parts]


def text_projection(parts: list[ContentPart]) -> str:
    chunks: list[str] = []
    for part in parts:
        if isinstance(part, TextPart):
            chunks.append(part.text)
        elif isinstance(part, ImagePart):
            chunks.append(f"[image:{part.attachment_id}]")
        elif isinstance(part, FilePart):
            chunks.append(f"[file:{part.attachment_id}]")
        elif isinstance(part, AudioPart):
            chunks.append(f"[audio:{part.attachment_id}]")
        elif isinstance(part, VideoPart):
            chunks.append(f"[video:{part.attachment_id}]")
    return "\n".join(chunk for chunk in chunks if chunk)
