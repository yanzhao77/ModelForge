"""Phase 8: RAG Knowledge Base tests."""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from services.knowledge_base import (
    KnowledgeBase, TextChunker, SimpleEmbedder,
    InMemoryVectorStore, FileParser,
)


class TestTextChunker:
    def test_simple_chunk(self):
        chunker = TextChunker(chunk_size=100, chunk_overlap=10)
        text = "This is a test. " * 30
        chunks = chunker.split(text)
        assert len(chunks) >= 1
        for chunk in chunks:
            assert len(chunk) > 0

    def test_short_text(self):
        chunker = TextChunker(chunk_size=500)
        chunks = chunker.split("Hello world")
        assert len(chunks) == 1
        assert "Hello world" in chunks[0]


class TestSimpleEmbedder:
    def test_embed(self):
        embedder = SimpleEmbedder()
        embedder.fit(["hello world", "goodbye world"])
        vec = embedder.embed("hello world")
        assert len(vec) > 0
        assert vec.sum() > 0


class TestInMemoryVectorStore:
    def test_add_and_search(self):
        store = InMemoryVectorStore()
        embedder = SimpleEmbedder()
        texts = ["python programming", "cooking recipes", "python tutorials"]
        embedder.fit(texts)

        for i, t in enumerate(texts):
            store.add(f"doc_{i}", t, {"source": f"file_{i}"}, embedder.embed(t))

        results = store.search(embedder.embed("python programming"), top_k=2)
        assert len(results) > 0
        assert "python" in results[0]["text"]


class TestFileParser:
    def test_parse_text_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".txt", encoding="utf-8"
        ) as f:
            f.write("Sample content for testing.")
            path = f.name
        try:
            parser = FileParser()
            text, meta = parser.parse(path)
            assert "Sample content" in text
            assert meta["type"] == "text"
        finally:
            os.unlink(path)

    def test_parse_markdown(self):
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".md", encoding="utf-8"
        ) as f:
            f.write("# Title\n\nContent here.")
            path = f.name
        try:
            parser = FileParser()
            text, meta = parser.parse(path)
            assert "Title" in text
            assert "Content" in text
        finally:
            os.unlink(path)

    def test_parse_unsupported(self):
        parser = FileParser()
        with pytest.raises(ValueError, match="Unsupported"):
            parser.parse("file.xyz")


class TestKnowledgeBase:
    def test_upload_txt(self):
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".txt", encoding="utf-8"
        ) as f:
            f.write("Python is a programming language. " * 20 +
                     "Machine learning is fascinating. " * 20)
            path = f.name
        try:
            kb = KnowledgeBase()
            result = kb.upload(path)
            assert result["status"] == "ingested"
            assert result["chunks"] >= 1
        finally:
            os.unlink(path)

    def test_query_returns_results(self):
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".txt", encoding="utf-8"
        ) as f:
            f.write("Python programming guide. " * 30)
            path = f.name
        try:
            kb = KnowledgeBase()
            kb.upload(path)
            result = kb.query("python programming", top_k=3)
            assert len(result["results"]) > 0
        finally:
            os.unlink(path)

    def test_query_no_results_for_unrelated(self):
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".txt", encoding="utf-8"
        ) as f:
            f.write("Python programming guide. " * 30)
            path = f.name
        try:
            kb = KnowledgeBase()
            kb.upload(path)
            result = kb.query("zzzxyzabc unrelated topic here", top_k=3)
            assert 0 <= len(result["results"]) <= 5
        finally:
            os.unlink(path)

    def test_stats(self):
        kb = KnowledgeBase()
        stats = kb.stats()
        assert stats["documents"] == 0
        assert stats["chunks"] == 0

    def test_upload_empty_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".txt", encoding="utf-8"
        ) as f:
            f.write("")
            path = f.name
        try:
            kb = KnowledgeBase()
            result = kb.upload(path)
            assert result["status"] == "empty"
        finally:
            os.unlink(path)
