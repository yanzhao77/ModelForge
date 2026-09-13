"""Example ModelForge plugin: a READ_ONLY tool.

Install it from the Extensions page (or `POST /api/v1/plugins/load` with
`{"manifest_path": "examples/plugins/word_count/plugin.json"}`).
"""
from __future__ import annotations


def word_count(text: str, context=None) -> dict:  # noqa: ARG001 - plugin contract
    """Return a small, deterministic summary of the given text."""
    lines = [line for line in str(text or "").splitlines() if line.strip()]
    return {
        "characters": len(text or ""),
        "words": len((text or "").split()),
        "lines": len(lines),
    }


def get_tools(ctx=None):  # noqa: ARG001 - plugin contract
    return {"examples.word_count": word_count}


def setup(ctx=None):  # noqa: ARG001 - plugin contract
    return {"status": "ready", "tools": ["examples.word_count"]}
