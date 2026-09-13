"""Hitting the vocabulary ceiling must be observable, not a silent outage.

Once MAX_VOCAB is reached, new terms are not indexed and any document made only
of them can never be retrieved. The cap used to be applied without a counter, a
log line or a metric, so retrieval just returned nothing.
"""
from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from services.knowledge_base import KnowledgeBase, SimpleEmbedder  # noqa: E402


def test_dropped_terms_are_counted_and_logged(monkeypatch, caplog):
    monkeypatch.setattr(SimpleEmbedder, "MAX_VOCAB", 5)
    embedder = SimpleEmbedder()

    with caplog.at_level(logging.WARNING):
        embedder.fit(["alpha beta gamma delta epsilon zeta eta"])

    assert len(embedder.vocab) == 5
    assert embedder.capped is True
    assert embedder.dropped_terms == 2
    assert "cap" in caplog.text


def test_stats_expose_the_capped_vocabulary(monkeypatch, tmp_path):
    monkeypatch.setattr(SimpleEmbedder, "MAX_VOCAB", 4)
    path = tmp_path / "doc.txt"
    path.write_text("alpha beta gamma delta epsilon zeta", encoding="utf-8")

    kb = KnowledgeBase()
    kb.upload(str(path), filename="doc.txt")
    stats = kb.stats()

    assert stats["vocab_size"] == 4
    assert stats["vocab_capped"] is True
    assert stats["vocab_dropped_terms"] > 0


def test_question_without_indexed_terms_is_reported(caplog, tmp_path):
    path = tmp_path / "doc.txt"
    path.write_text("deployment runbook steps", encoding="utf-8")
    kb = KnowledgeBase()
    kb.upload(str(path), filename="doc.txt")

    with caplog.at_level(logging.WARNING):
        result = kb.query("zzz-qqq", top_k=3)

    assert result["total_results"] == 0
    assert "matched no indexed term" in caplog.text
