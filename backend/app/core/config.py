"""ModelForge 2.0 Configuration System.

Loads config from config.yaml, .env, and os.environ (env overrides yaml).
"""
import os
import secrets
from pathlib import Path
from urllib.parse import urlparse

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

_INSECURE_JWT_SECRETS = {"", "modelforge-dev-secret-change-me-0123456789abcdef", "dev-secret"}
_PRODUCTION_ENVIRONMENTS = {"prod", "production"}


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
    command_execution_enabled: bool = False


class PolicySettings(BaseModel):
    """Default run policy (config.yaml -> policy:)."""
    default_network_access: bool = False
    default_shell_access: bool = False
    # File reads can expose process credentials and other users' data. They are
    # disabled unless a specific agent policy opts in.
    default_filesystem_access: bool = False


class Settings(BaseModel):
    # 基础
    model_path: str = "./models"
    database_path: str = "./data/modelforge.db"
    log_level: str = "INFO"
    environment: str = "development"
    # 认证
    jwt_secret: str = ""
    jwt_expire_minutes: int = 60 * 24 * 7
    # Comma-separated accounts allowed to administer process-wide runtime state.
    runtime_admin_usernames: str = ""
    cors_allow_origins: str = "http://localhost:3000,http://localhost:5173"
    session_cookie_name: str = "modelforge_session"
    csrf_cookie_name: str = "modelforge_csrf"
    session_cookie_secure: bool = False
    session_cookie_samesite: str = "lax"
    # 运行时
    ollama_base_url: str = "http://localhost:11434"
    enable_streaming: bool = True
    # 模型/下载
    hf_endpoint: str = "https://hf-mirror.com"
    model_dir: str = "./models"
    data_dir: str = "./data"
    # Each Agent user receives a child directory under this root. Built-in file
    # tools must not resolve paths outside that per-user workspace.
    agent_workspace_root: str = "./data/workspaces"
    agent_file_read_max_bytes: int = 512 * 1024
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
    # OpenAI-compatible API resource governance
    openai_max_concurrent_per_user: int = 4
    openai_rate_limit_window_seconds: int = 60
    openai_rate_limit_max_requests: int = 60
    openai_inference_timeout_seconds: int = 120
    # 3.x Plugins
    plugins_dir: str = "./plugins"

    @property
    def is_production(self) -> bool:
        """Whether this process is running with production security invariants."""
        return self.environment in _PRODUCTION_ENVIRONMENTS

    @property
    def cors_origins(self) -> list[str]:
        """Return normalized, explicit browser origins for CORS middleware."""
        return [origin.strip().rstrip("/") for origin in self.cors_allow_origins.split(",") if origin.strip()]



def _validate_production_origins(origins: list[str]) -> None:
    """Reject wildcard and non-HTTPS origins when credentialed production CORS is enabled."""
    if not origins:
        raise RuntimeError("CORS_ALLOW_ORIGINS must list at least one HTTPS origin in production")
    for origin in origins:
        parsed = urlparse(origin)
        if origin == "*" or parsed.scheme != "https" or not parsed.netloc or parsed.path not in {"", "/"}:
            raise RuntimeError(
                "CORS_ALLOW_ORIGINS must contain explicit HTTPS origins without paths when MODELFORGE_ENV=production"
            )
def load_config(config_path: str | None = None) -> Settings:
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
        "RUNTIME_ADMIN_USERNAMES": "runtime_admin_usernames",
        "CORS_ALLOW_ORIGINS": "cors_allow_origins",
        "SESSION_COOKIE_NAME": "session_cookie_name",
        "CSRF_COOKIE_NAME": "csrf_cookie_name",
        "SESSION_COOKIE_SECURE": "session_cookie_secure",
        "SESSION_COOKIE_SAMESITE": "session_cookie_samesite",
        "OLLAMA_BASE_URL": "ollama_base_url",
        "HF_ENDPOINT": "hf_endpoint",
        "MODEL_DIR": "model_dir",
        "DATA_DIR": "data_dir",
        "AGENT_WORKSPACE_ROOT": "agent_workspace_root",
        "AGENT_FILE_READ_MAX_BYTES": "agent_file_read_max_bytes",
        "DATASET_DIR": "dataset_dir",
        "TRAIN_OUTPUT_DIR": "train_output_dir",
        "MAX_DATASET_SIZE": "max_dataset_size",
        "OPENAI_MAX_CONCURRENT_PER_USER": "openai_max_concurrent_per_user",
        "OPENAI_RATE_LIMIT_WINDOW_SECONDS": "openai_rate_limit_window_seconds",
        "OPENAI_RATE_LIMIT_MAX_REQUESTS": "openai_rate_limit_max_requests",
        "OPENAI_INFERENCE_TIMEOUT_SECONDS": "openai_inference_timeout_seconds",
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
        "TOOLS_COMMAND_EXECUTION_ENABLED": ("tools", "command_execution_enabled"),
        "POLICY_DEFAULT_NETWORK_ACCESS": ("policy", "default_network_access"),
        "POLICY_DEFAULT_SHELL_ACCESS": ("policy", "default_shell_access"),
        "POLICY_DEFAULT_FILESYSTEM_ACCESS": ("policy", "default_filesystem_access"),
    }
    for env_key, (section, field) in nested_env.items():
        env_val = os.getenv(env_key)
        if env_val is not None:
            data.setdefault(section, {})[field] = env_val

    known = {k: v for k, v in data.items() if k in Settings.model_fields}
    result = Settings(**known)
    environment = os.getenv("MODELFORGE_ENV", os.getenv("APP_ENV", "development")).strip().lower()
    result.environment = environment
    secret = (result.jwt_secret or "").strip()
    if environment in _PRODUCTION_ENVIRONMENTS:
        if secret in _INSECURE_JWT_SECRETS or len(secret) < 32:
            raise RuntimeError(
                "JWT_SECRET must be set to a non-default value of at least 32 characters when MODELFORGE_ENV=production"
            )
        _validate_production_origins(result.cors_origins)
        # Credentialed cross-site browser sessions must never downgrade to insecure defaults.
        result.session_cookie_secure = True
        result.session_cookie_samesite = "none"
    elif secret in _INSECURE_JWT_SECRETS:
        # Do not silently sign development JWTs with a public, predictable key.
        # Persist the generated secret to survive process restarts during development.
        secret_path = Path(result.data_dir) / ".dev_jwt_secret"
        try:
            if secret_path.exists():
                persisted = secret_path.read_text(encoding="utf-8").strip()
                if len(persisted) >= 32:
                    result.jwt_secret = persisted
                    return result
            generated = secrets.token_urlsafe(48)
            secret_path.parent.mkdir(parents=True, exist_ok=True)
            secret_path.write_text(generated, encoding="utf-8")
            os.chmod(str(secret_path), 0o600)
            result.jwt_secret = generated
        except OSError:
            result.jwt_secret = secrets.token_urlsafe(48)
    return result


# 进程级共享配置（启动时加载一次）
settings = load_config()
