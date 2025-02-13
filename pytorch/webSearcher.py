from duckduckgo_search import DDGS
from functools import lru_cache


class WebSearcher:
    @staticmethod
    def duckduckgo_search(query: str, max_results: int = 5):
        """执行网络搜索并返回简明结果"""
        with DDGS() as ddgs:
            results = []
            for result in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": result["title"],
                    "content": result["body"][:2048]  # 截断内容避免过长
                })
            return results

    @lru_cache(maxsize=100)
    def cached_search(query: str):
        return WebSearcher.duckduckgo_search(query)
