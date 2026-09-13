"""The chunker must always terminate and stay within its configured size.

A long paragraph whose last space sits inside the overlap window (long CJK
documents, "摘要: " + body, PDF-extracted text) used to slice ``current`` with
the same offset on every pass. That loop ran inside an ``async def`` endpoint,
so one ordinary upload froze every request in the process until a restart.
"""
from __future__ import annotations

import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from services.knowledge_base import KnowledgeBase, TextChunker  # noqa: E402

DEADLINE_SECONDS = 5.0
# Single paragraph: the trailing space of "摘要: " lands early in the first
# window and there is no space after it, which is what used to loop forever.
CJK_PARAGRAPH = "摘要: " + "这是一段很长的中文说明文字，用来验证切块逻辑不会卡住。" * 30


def _with_deadline(func):
    """Run ``func`` on a daemon thread so a regression fails instead of hanging."""
    box: list[object] = []
    thread = threading.Thread(target=lambda: box.append(func()), daemon=True)
    thread.start()
    thread.join(DEADLINE_SECONDS)
    assert box, f"knowledge ingestion did not finish within {DEADLINE_SECONDS:.0f}s"
    return box[0]


def test_long_cjk_paragraph_with_early_space_terminates():
    chunks = _with_deadline(lambda: TextChunker().split(CJK_PARAGRAPH))

    assert chunks
    assert "摘要" in chunks[0]


def test_ascii_space_before_the_overlap_window_terminates():
    chunks = _with_deadline(lambda: TextChunker().split("a " + "x" * 2000))

    assert chunks


def test_long_runs_without_any_space_terminate():
    assert _with_deadline(lambda: TextChunker().split("中文" * 800))


def test_chunks_stay_within_the_configured_size():
    chunker = TextChunker(chunk_size=100, chunk_overlap=10)

    for text in (CJK_PARAGRAPH, "a " + "x" * 1000, "word " * 300, "intro\n\n" + "x" * 900):
        chunks = _with_deadline(lambda: chunker.split(text))

        assert chunks
        assert max(len(chunk) for chunk in chunks) <= chunker.chunk_size


def test_overlap_at_or_above_the_chunk_size_is_clamped():
    chunker = TextChunker(chunk_size=50, chunk_overlap=500)
    chunks = _with_deadline(lambda: chunker.split("hello world " * 50))

    assert chunks
    assert max(len(chunk) for chunk in chunks) <= 50


def test_whitespace_only_chunks_are_not_indexed():
    chunker = TextChunker(chunk_size=8, chunk_overlap=2)
    chunks = _with_deadline(lambda: chunker.split("ab" + " " * 40 + "cd"))

    assert chunks
    assert all(chunk.strip() for chunk in chunks)
    assert "ab" in chunks[0]
    assert "cd" in chunks[-1]


def test_upload_of_a_triggering_document_finishes(tmp_path):
    path = tmp_path / "zh.md"
    path.write_text(CJK_PARAGRAPH, encoding="utf-8")

    result = _with_deadline(
        lambda: KnowledgeBase().upload(str(path), filename="zh.md")
    )

    assert result["status"] == "ingested"
    assert result["chunks"] >= 1
