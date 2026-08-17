"""Security regression tests for untrusted local Transformers model loading."""
import asyncio
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "app"))


def test_local_runtime_disables_remote_repository_code(monkeypatch):
    from services.runtimes.local_runtime import LocalRuntime

    tokenizer_calls = []
    model_calls = []

    class FakeTokenizer:
        @staticmethod
        def from_pretrained(path, **kwargs):
            tokenizer_calls.append((path, kwargs))
            return object()

    class FakeModel:
        def to(self, device):
            assert device == "cpu"
            return self

        def eval(self):
            return self

    class FakeModelFactory:
        @staticmethod
        def from_pretrained(path, **kwargs):
            model_calls.append((path, kwargs))
            return FakeModel()

    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: False),
        float32="float32",
        float16="float16",
    )
    fake_transformers = types.SimpleNamespace(
        AutoTokenizer=FakeTokenizer,
        AutoModelForCausalLM=FakeModelFactory,
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    runtime = LocalRuntime(model_path="/nonexistent/untrusted-model")
    result = asyncio.run(runtime.load("ignored"))

    assert result["status"] == "loaded"
    assert tokenizer_calls[0][1]["trust_remote_code"] is False
    assert model_calls[0][1]["trust_remote_code"] is False
