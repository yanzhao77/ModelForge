"""Parsing an upload must not materialise every row in memory."""
from __future__ import annotations

import json
import os
import sys
import tracemalloc

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from services.dataset_service import DatasetParser  # noqa: E402


def _peak_parse_bytes(path: str, fmt: str) -> tuple[int, int, tuple]:
    tracemalloc.start()
    try:
        result = DatasetParser.parse(path, fmt)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak, result[0], result


def test_large_jsonl_keeps_only_the_sample(tmp_path):
    path = tmp_path / "big.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for index in range(20_000):
            handle.write(json.dumps({"text": f"row {index}"}, ensure_ascii=False) + "\n")

    peak, count, (_count, columns, sample) = _peak_parse_bytes(str(path), "jsonl")

    assert count == 20_000
    assert columns == ["text"]
    assert len(sample) == DatasetParser.SAMPLE_ROWS
    assert sample[0] == {"text": "row 0"}
    # The previous implementation materialised every row (~6x the file size).
    assert peak < path.stat().st_size * 2


def test_large_csv_keeps_only_the_sample(tmp_path):
    path = tmp_path / "big.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("a,b\n")
        for index in range(20_000):
            handle.write(f"{index},{index * 2}\n")

    peak, count, (_count, columns, sample) = _peak_parse_bytes(str(path), "csv")

    assert count == 20_000
    assert columns == ["a", "b"]
    assert len(sample) == DatasetParser.SAMPLE_ROWS
    assert peak < path.stat().st_size * 2


def test_text_dataset_counts_every_line_but_samples_five(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("\n".join(f"line {index}" for index in range(50)), encoding="utf-8")

    count, columns, sample = DatasetParser.parse(str(path), "txt")

    assert count == 50
    assert columns == ["text"]
    assert sample == [{"text": f"line {index}"} for index in range(5)]
