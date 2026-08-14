"""Online search service (DuckDuckGo), ported from legacy webSearcher.py."""
from functools import lru_cache
from typing import List, Dict

_SEARCH_KEYWORDS = ["最新", "当前", "现在", "搜索", "过去", "推荐", "新闻", "实时", "怎么安装", "如何配置"]


def needs_web_search(question: str) -> bool:
    """Keyword-based heuristic for whether a question needs online search."""
    return any(kw in (question or "") for kw in _SEARCH_KEYWORDS)


@lru_cache(maxsize=100)
def cached_search(query: str, max_results: int = 5) -> List[Dict]:
    """Cached DuckDuckGo search. Returns [{"title","content"}, ...]."""
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for result in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": result.get("title", ""),
                    "content": (result.get("body") or "")[:2048],
                })
        return results
    except Exception:
        return []


def format_search_context(results: List[Dict]) -> str:
    if not results:
        return ""
    lines = [f"- {item['title']}: {item['content']}" for item in results]
    return "\n".join(lines)