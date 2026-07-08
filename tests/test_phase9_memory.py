"""Phase 9: Memory System tests."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from services.memory import ConversationMemory, LongTermMemory, MemoryManager


class TestConversationMemory:

    def test_add_and_get(self):
        mem = ConversationMemory()
        mem.add("s1", "user", "Hello")
        mem.add("s1", "assistant", "Hi there")
        msgs = mem.get("s1")
        assert len(msgs) == 2
        assert msgs[0]["content"] == "Hello"
        assert msgs[1]["content"] == "Hi there"

    def test_get_with_limit(self):
        mem = ConversationMemory()
        for i in range(10):
            mem.add("s1", "user", f"msg{i}")
        msgs = mem.get("s1", limit=3)
        assert len(msgs) == 3

    def test_trim_old_messages(self):
        mem = ConversationMemory(max_messages=5)
        for i in range(10):
            mem.add("s1", "user", f"msg{i}")
        msgs = mem.get("s1")
        assert len(msgs) <= 5

    def test_clear(self):
        mem = ConversationMemory()
        mem.add("s1", "user", "test")
        mem.clear("s1")
        assert mem.get("s1") == []

    def test_get_nonexistent_session(self):
        mem = ConversationMemory()
        assert mem.get("nonexistent") == []

    def test_summary(self):
        mem = ConversationMemory()
        mem.add("s1", "user", "What is AI?")
        mem.add("s1", "assistant", "AI is artificial intelligence.")
        summary = mem.summary("s1")
        assert "messages" in summary
        assert "What is AI" in summary or "artificial" in summary

    def test_summary_empty(self):
        mem = ConversationMemory()
        assert mem.summary("empty") == "No conversation history."


class TestLongTermMemory:

    def test_remember_and_recall(self):
        mem = LongTermMemory()
        mem.remember("s1", "Python is a programming language")
        mem.remember("s1", "Cooking requires fresh ingredients")
        results = mem.recall("python programming")
        assert len(results) > 0
        assert "Python" in results[0]["text"]

    def test_recall_no_match(self):
        mem = LongTermMemory()
        mem.remember("s1", "Python coding")
        results = mem.recall("xyzabc123")
        assert 0 <= len(results) <= 1

    def test_stats(self):
        mem = LongTermMemory()
        mem.remember("s1", "fact one")
        mem.remember("s2", "fact two")
        stats = mem.stats()
        assert stats["total_memories"] == 2


class TestMemoryManager:

    def test_add_and_get_conversation(self):
        mgr = MemoryManager()
        mgr.add_message("s1", "user", "hello")
        mgr.add_message("s1", "assistant", "world")
        msgs = mgr.get_conversation("s1")
        assert len(msgs) == 2

    def test_remember_and_recall(self):
        mgr = MemoryManager()
        mgr.remember("s1", "Machine learning is fascinating")
        results = mgr.recall("machine learning")
        assert len(results) > 0

    def test_clear_session(self):
        mgr = MemoryManager()
        mgr.add_message("s1", "user", "test")
        mgr.add_message("s1", "assistant", "response")
        mgr.clear_session("s1")
        assert mgr.get_conversation("s1") == []

    def test_stats(self):
        mgr = MemoryManager()
        mgr.add_message("s1", "user", "hi")
        mgr.remember("s1", "fact")
        stats = mgr.stats()
        assert "short_term_sessions" in stats
        assert "long_term" in stats