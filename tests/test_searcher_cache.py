"""The web-search helper must cache successes, never failures."""
from __future__ import annotations

import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from services import searcher  # noqa: E402


def _install_ddgs(monkeypatch, handler) -> None:
    module = types.ModuleType("duckduckgo_search")

    class DDGS:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def text(self, query, max_results=5):
            return handler(query, max_results)

    module.DDGS = DDGS
    monkeypatch.setitem(sys.modules, "duckduckgo_search", module)
    searcher._search.cache_clear()


def test_successful_search_is_cached(monkeypatch):
    calls = {"count": 0}

    def handler(query, max_results):
        calls["count"] += 1
        return [{"title": "t", "body": "body text"}]

    _install_ddgs(monkeypatch, handler)

    first = searcher.cached_search("cached query")
    second = searcher.cached_search("cached query")

    assert first == [{"title": "t", "content": "body text"}]
    assert second == first
    assert calls["count"] == 1


def test_failed_search_is_not_cached(monkeypatch):
    calls = {"count": 0}

    def handler(query, max_results):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("upstream unavailable")
        return [{"title": "t", "body": "recovered"}]

    _install_ddgs(monkeypatch, handler)

    assert searcher.cached_search("flaky query") == []
    assert searcher.cached_search("flaky query") == [{"title": "t", "content": "recovered"}]
    assert calls["count"] == 2


def test_missing_search_dependency_returns_empty(monkeypatch):
    monkeypatch.setitem(sys.modules, "duckduckgo_search", None)
    searcher._search.cache_clear()

    with pytest.raises(Exception):
        searcher._search("no dependency")
    assert searcher.cached_search("no dependency") == []
