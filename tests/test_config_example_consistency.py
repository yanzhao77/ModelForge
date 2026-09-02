"""config.example.yaml must not silently drift from code defaults (MF-CONFIG-001)."""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(__file__))
APP = os.path.join(ROOT, "backend", "app")
if APP not in sys.path:
    sys.path.insert(0, APP)

EXAMPLE_YAML = os.path.join(ROOT, "config.example.yaml")

from core.config import PolicySettings, Settings, load_config  # noqa: E402
from runtime.policy.engine import Policy  # noqa: E402


def _example_settings() -> Settings:
    return load_config(config_path=EXAMPLE_YAML)


def _code_default_settings() -> Settings:
    return Settings()


def test_example_policy_defaults_match_code_defaults():
    example = _example_settings()
    code = _code_default_settings()
    assert example.policy.default_network_access == code.policy.default_network_access
    assert example.policy.default_shell_access == code.policy.default_shell_access
    assert example.policy.default_filesystem_access == code.policy.default_filesystem_access


def test_example_config_is_default_deny_on_filesystem():
    example = _example_settings()
    assert example.policy.default_filesystem_access is False


def test_code_default_dataset_deny():
    # The hardening intent: these high-risk capabilities must be off by default.
    assert _code_default_settings().policy.default_network_access is False
    assert _code_default_settings().policy.default_shell_access is False
    assert _code_default_settings().policy.default_filesystem_access is False


def test_policy_from_settings_matches_example_defaults():
    example_defaults = _example_settings().policy
    policy = Policy.from_settings(_example_settings())
    assert policy.network_access == example_defaults.default_network_access
    assert policy.shell_access == example_defaults.default_shell_access
    assert policy.filesystem_access == example_defaults.default_filesystem_access


def test_example_policy_fields_reference_code_schema():
    assert set(PolicySettings.model_fields.keys()) >= {"default_network_access", "default_shell_access", "default_filesystem_access"}


def test_load_config_parses_example_marker_fields():
    example = _example_settings()
    # Guards against silently falling back to defaults and masking drift.
    assert example.policy.default_network_access is False
