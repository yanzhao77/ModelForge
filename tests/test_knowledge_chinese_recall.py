"""Chinese documents must be retrievable from natural-language questions.

Without word segmentation a whole Chinese sentence used to collapse into a
single bag-of-words token, so a question that contained the stored keyword
verbatim still returned zero sources from the knowledge base.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from services.knowledge_base import KnowledgeBase, SimpleEmbedder  # noqa: E402

DEPLOY_DOC = (
    "模型部署需要先安装依赖并配置环境变量。\n\n"
    "如果显存不足，可以降低 batch size 或使用量化模型。\n"
)
TRAINING_DOC = "训练任务失败时，请先检查数据集格式与学习率设置。\n"


def _write(tmp_path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_chinese_runs_are_split_into_overlapping_bigrams():
    tokens = SimpleEmbedder()._tokenize("模型部署")

    assert "模型" in tokens
    assert "型部" in tokens
    # A whole sentence must never stay a single token.
    single = SimpleEmbedder()._tokenize("模型部署需要先安装依赖并配置环境变量")
    assert len(single) > 1


def test_chinese_substring_query_returns_the_document(tmp_path):
    kb = KnowledgeBase()
    kb.upload(_write(tmp_path, "deploy.txt", DEPLOY_DOC), filename="deploy.txt")

    for question in ("安装依赖", "显存不足", "降低 batch size"):
        result = kb.query(question, top_k=3)
        assert result["total_results"] >= 1, question
        assert result["results"][0]["score"] > 0
        assert "模型部署" in result["results"][0]["text"]


def test_query_of_a_different_document_still_ranks_the_owner(tmp_path):
    kb = KnowledgeBase()
    kb.upload(_write(tmp_path, "deploy.txt", DEPLOY_DOC), filename="deploy.txt")
    # The second upload extends the shared vocabulary; the first document's
    # vector must stay usable (previously the whole corpus was re-embedded).
    kb.upload(_write(tmp_path, "train.txt", TRAINING_DOC), filename="train.txt")

    deploy = kb.query("安装依赖", top_k=2)
    assert deploy["results"][0]["source"] == "deploy.txt"

    training = kb.query("学习率设置", top_k=2)
    assert training["results"][0]["source"] == "train.txt"


def test_english_retrieval_is_unchanged(tmp_path):
    kb = KnowledgeBase()
    kb.upload(
        _write(tmp_path, "en.txt", "Deployment requires installing dependencies first.\n"),
        filename="en.txt",
    )

    result = kb.query("installing dependencies", top_k=3)
    assert result["total_results"] >= 1


def test_vocabulary_stays_bounded(monkeypatch):
    """A long-running server must not grow the token table without limit."""
    monkeypatch.setattr(SimpleEmbedder, "MAX_VOCAB", 4)
    embedder = SimpleEmbedder()
    embedder.fit(["alpha beta gamma delta epsilon zeta"])

    assert len(embedder.vocab) == 4
    assert embedder.embed("alpha beta").shape == (4,)
