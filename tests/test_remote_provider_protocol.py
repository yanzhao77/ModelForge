import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "backend" / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from services.remote_provider_service import RemoteProviderError, normalize_base_url
from services.runtimes.openai_api_runtime import OpenAIRuntime


def test_remote_provider_requires_https_except_loopback():
    assert normalize_base_url("http://127.0.0.1:1234/v1") == "http://127.0.0.1:1234/v1"
    assert normalize_base_url("https://api.example.com/v1/") == "https://api.example.com/v1"
    try:
        normalize_base_url("http://api.example.com/v1")
    except RemoteProviderError as exc:
        assert "HTTPS" in str(exc)
    else:
        raise AssertionError("non-local HTTP must be rejected")


def test_responses_output_text_is_normalized():
    payload = {"output": [{"type": "message", "content": [
        {"type": "output_text", "text": "hello "},
        {"type": "output_text", "text": "world"},
    ]}]}
    assert OpenAIRuntime._responses_text(payload) == "hello world"


def test_remote_runtime_never_treats_stop_as_provider_side_termination():
    import asyncio
    runtime = OpenAIRuntime("secret", "https://api.example.com/v1", "example", "responses")
    assert asyncio.run(runtime.stop("example")) == {"status": "detached", "model": "example", "remote": True}
