"""ModelForge 2.0 Configuration System.

Loads config from config.yaml and .env (env overrides yaml).
"""
import os
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel


class Settings(BaseModel):
    model_path: str = "./models"
    database_path: str = "./data/modelforge.db"
    log_level: str = "INFO"


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
    }
    for env_key, field_name in env_map.items():
        env_val = os.getenv(env_key)
        if env_val is not None:
            data[field_name] = env_val

    return Settings(**{k: v for k, v in data.items() if k in Settings.model_fields})
