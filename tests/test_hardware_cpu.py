"""Explicit CPU inference smoke against a pre-provisioned local Transformers model."""

from __future__ import annotations

import os

import pytest


@pytest.mark.real_model
def test_cpu_transformers_inference_with_preprovisioned_model():
    model_path = os.getenv("MODELFORGE_CPU_SMOKE_MODEL", "").strip()
    if not model_path:
        pytest.skip("Set MODELFORGE_CPU_SMOKE_MODEL to an existing local model directory.")

    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    tokenizer = transformers.AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    model = transformers.AutoModelForCausalLM.from_pretrained(model_path, local_files_only=True)
    encoded = tokenizer("ModelForge CPU smoke", return_tensors="pt")
    with torch.no_grad():
        output = model(**encoded)
    assert output.logits.shape[0] == 1
    assert output.logits.device.type == "cpu"
