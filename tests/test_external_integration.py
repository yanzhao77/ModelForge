"""Opt-in public Hugging Face connectivity smoke test.

The test is deliberately disabled unless RUN_NETWORK_TESTS=1, so normal unit
and offline CI remain deterministic while a dedicated job verifies real access.
"""
import os

import pytest


@pytest.mark.network
@pytest.mark.real_model
def test_public_huggingface_model_metadata_is_reachable():
    if os.getenv("RUN_NETWORK_TESTS") != "1":
        pytest.skip("set RUN_NETWORK_TESTS=1 to execute external integration tests")
    hub = pytest.importorskip("huggingface_hub")
    info = hub.model_info("sshleifer/tiny-gpt2")
    assert info.id == "sshleifer/tiny-gpt2"
