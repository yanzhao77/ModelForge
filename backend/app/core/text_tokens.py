"""CJK-aware term extraction shared by retrieval helpers.

Chinese text has no spaces, so a whole sentence used to become one search
term and retrieval failed quietly even when the query contained a stored
keyword verbatim. These helpers keep the previous behaviour for every
non-CJK script and expand CJK runs into overlapping bigrams, which makes
substring queries match without a word segmenter.
"""
from __future__ import annotations

import re
from collections.abc import Iterator

_WORD_RUN = re.compile(r"\w+")
_CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")


def iter_terms(text: str) -> Iterator[str]:
    """Yield search terms: ASCII/all scripts verbatim, CJK runs as bigrams."""
    for run in _WORD_RUN.findall((text or "").lower()):
        if not _CJK_RUN.search(run):
            yield run
            continue
        position = 0
        for match in _CJK_RUN.finditer(run):
            if match.start() > position:
                yield run[position:match.start()]
            segment = match.group()
            if len(segment) == 1:
                yield segment
            else:
                yield from (segment[index:index + 2] for index in range(len(segment) - 1))
            position = match.end()
        if position < len(run):
            yield run[position:]
