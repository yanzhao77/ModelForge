"""ModelForge 2.0 Configuration System.

Loads config from config.yaml, .env, and os.environ (env overrides yaml).
"""
import os
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel


class RuntimeSettings(BaseModel):
    """3.0 Agent Runtime limits (config.yaml -> runtime:)."""
    max_iterations: int = 20
    max_tool_calls: int = 50
    timeout_seconds: int = 600
    event_persistence: bool = True
    event_retention_days: int = 30


class ToolsSettings(BaseModel):
    """Tool execution defaults (config.yaml -> tools:)."""
    default_timeout_seconds: int = 60


class PolicySettings(BaseModel):
    """Default run policy (config.yaml -> policy:)."""
    default_network_access: bool = False
    default_shell_access: bool = False
    default_filesystem_access: bool = True


class Settings(BaseModel):
    # 基础
    model_path: str = "./models"
    database_path: str = "./data/modelforge.db"
    log_level: str = "INFO"
    # 认证
    jwt_secret: str = "modelforge-dev-secret-change-me-0123456789abcdef"
    jwt_expire_minutes: int = 60 * 24 * 7
    # 运行时
    ollama_base_url: str = "http://localhost:11434"
    enable_streaming: bool = True
    # 模型/下载
    hf_endpoint: str = "https://hf-mirror.com"
    model_dir: str = "./models"
    data_dir: str = "./data"
    max_upload_size: int = 100 * 1024 * 1024  # 100MB
    # 数据集 / 训练 / 知识库
    max_dataset_size: int = 200 * 1024 * 1024  # 200MB
    dataset_dir: str = "./data/datasets"
    train_output_dir: str = "./outputs"
    train_max_workers: int = 1
    kb_persist: bool = True
    # 3.0 Agent Runtime
    runtime: RuntimeSettings = RuntimeSettings()
    tools: ToolsSettings = ToolsSettings()
    policy: PolicySettings = PolicySettings()
    # 3.x Plugins
    plugins_dir: str = "./plugins"


def load_config(config_path: Optional[str] = None) -> Settings:
    """Load settings from config.yaml, then override with .env and os.environ."""
    base_dir = Path(__file__).resolve().parents[3]  # ModelForge root
    data: dict = {}

    # 1. Load config.yaml
    yaml_path = config_path or str(base_dir / "config.yaml")
    if os.path.exists(yaml_path):
        with open(yaml_path, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f) or {}
            data.update(yaml_data)

    # 2. Load .env only when using the default project config
    if config_path is None:
        env_path = str(base_dir / ".env")
        load_dotenv(env_path, override=False)

    # 3. Env vars override yaml (highest priority)
    env_map = {
        "MODEL_PATH": "model_path",
        "DATABASE_PATH": "database_path",
        "LOG_LEVEL": "log_level",
        "JWT_SECRET": "jwt_secret",
        "OLLAMA_BASE_URL": "ollama_base_url",
        "HF_ENDPOINT": "hf_endpoint",
        "MODEL_DIR": "model_dir",
        "DATA_DIR": "data_dir",
        "DATASET_DIR": "dataset_dir",
        "TRAIN_OUTPUT_DIR": "train_output_dir",
        "MAX_DATASET_SIZE": "max_dataset_size",
    }
    for env_key, field_name in env_map.items():
        env_val = os.getenv(env_key)
        if env_val is not None:
            data[field_name] = env_val

    # Nested section env overrides (RUNTIME_MAX_ITERATIONS -> runtime.max_iterations)
    nested_env = {
        "RUNTIME_MAX_ITERATIONS": ("runtime", "max_iterations"),
        "RUNTIME_MAX_TOOL_CALLS": ("runtime", "max_tool_calls"),
        "RUNTIME_TIMEOUT_SECONDS": ("runtime", "timeout_seconds"),
        "RUNTIME_EVENT_PERSISTENCE": ("runtime", "event_persistence"),
        "RUNTIME_EVENT_RETENTION_DAYS": ("runtime", "event_retention_days"),
        "TOOL_DEFAULT_TIMEOUT_SECONDS": ("tools", "default_timeout_seconds"),
        "POLICY_DEFAULT_NETWORK_ACCESS": ("policy", "default_network_access"),
        "POLICY_DEFAULT_SHELL_ACCESS": ("policy", "default_shell_access"),
        "POLICY_DEFAULT_FILESYSTEM_ACCESS": ("policy", "default_filesystem_access"),
    }
    for env_key, (section, field) in nested_env.items():
        env_val = os.getenv(env_key)
        if env_val is not None:
            data.setdefault(section, {})[field] = env_val

    known = {k: v for k, v in data.items() if k in Settings.model_fields}
    return Settings(**known)


# 进程级共享配置（启动时加载一次）
settings = load_config()