"""User-scoped OpenAI-compatible provider configuration with encrypted keys."""
from __future__ import annotations

import base64
import datetime
import hashlib
import json
import os
import secrets
from pathlib import Path
from urllib.parse import urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken
from models.records import RemoteProviderConfig
from sqlalchemy.orm import Session


class RemoteProviderError(ValueError):
    pass


def _is_loopback(host: str | None) -> bool:
    return (host or "").lower() in {"localhost", "127.0.0.1", "::1"}


def normalize_base_url(value: str) -> str:
    url = value.strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise RemoteProviderError("Base URL must be a complete HTTP(S) URL without embedded credentials.")
    if parsed.scheme != "https" and not _is_loopback(parsed.hostname):
        raise RemoteProviderError("Remote provider URLs must use HTTPS. HTTP is allowed only for localhost.")
    return url


class ProviderCipher:
    """Fernet cipher backed by an explicit env key or a 0600 local key file."""

    def __init__(self, data_dir: str):
        self.path = Path(data_dir) / ".remote_provider_fernet.key"

    def _key(self) -> bytes:
        value = os.getenv("REMOTE_PROVIDER_ENCRYPTION_KEY", "").strip()
        if value:
            return value.encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            return self.path.read_bytes().strip()
        key = Fernet.generate_key()
        fd = os.open(str(self.path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(key)
        return key

    def encrypt(self, value: str) -> str:
        return Fernet(self._key()).encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, value: str) -> str:
        try:
            return Fernet(self._key()).decrypt(value.encode("utf-8")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise RemoteProviderError("The stored provider key cannot be decrypted. Re-enter the API key.") from exc


class RemoteProviderService:
    def __init__(self, db: Session, data_dir: str):
        self.db = db
        self.cipher = ProviderCipher(data_dir)

    def list(self, user_id: int) -> list[dict]:
        rows = self.db.query(RemoteProviderConfig).filter(RemoteProviderConfig.user_id == user_id).order_by(RemoteProviderConfig.name).all()
        return [row.to_public_dict() for row in rows]

    def save(self, user_id: int, *, name: str, base_url: str, protocol: str, default_model: str, api_key: str | None) -> dict:
        name = name.strip()
        if not name or len(name) > 100:
            raise RemoteProviderError("Provider name must contain 1–100 characters.")
        if protocol not in {"responses", "chat_completions"}:
            raise RemoteProviderError("Protocol must be responses or chat_completions.")
        if not default_model.strip():
            raise RemoteProviderError("A default model is required.")
        base_url = normalize_base_url(base_url)
        row = self.db.query(RemoteProviderConfig).filter(RemoteProviderConfig.user_id == user_id, RemoteProviderConfig.name == name).one_or_none()
        if row is None:
            if not api_key:
                raise RemoteProviderError("An API key is required for a new provider.")
            row = RemoteProviderConfig(user_id=user_id, name=name)
            self.db.add(row)
        row.base_url, row.protocol, row.default_model, row.enabled = base_url, protocol, default_model.strip(), True
        if api_key:
            row.key_ciphertext = self.cipher.encrypt(api_key.strip())
        self.db.commit()
        self.db.refresh(row)
        return row.to_public_dict()

    def delete(self, user_id: int, provider_id: int) -> None:
        row = self.db.query(RemoteProviderConfig).filter(RemoteProviderConfig.user_id == user_id, RemoteProviderConfig.id == provider_id).one_or_none()
        if row is None:
            raise RemoteProviderError("Provider not found.")
        self.db.delete(row)
        self.db.commit()

    def verify(self, user_id: int, provider_id: int) -> dict:
        row = self.db.query(RemoteProviderConfig).filter(RemoteProviderConfig.user_id == user_id, RemoteProviderConfig.id == provider_id).one_or_none()
        if row is None:
            raise RemoteProviderError("Provider not found.")
        api_key = self.cipher.decrypt(row.key_ciphertext)
        try:
            with httpx.Client(timeout=15.0, follow_redirects=False) as client:
                response = client.get(f"{row.base_url}/models", headers={"Authorization": f"Bearer {api_key}"})
            if response.status_code >= 400:
                code = (
                    "AUTHENTICATION_FAILED"
                    if response.status_code in {401, 403}
                    else "RATE_LIMITED"
                    if response.status_code == 429
                    else "PROVIDER_HTTP_ERROR"
                )
                self._record_verification(row, "failed", code, [])
                raise RemoteProviderError(f"Provider returned HTTP {response.status_code} while listing models.")
            data = response.json()
            items = data.get("data", data.get("models", [])) if isinstance(data, dict) else []
            models = [str(item.get("id") or item.get("name")) for item in items if isinstance(item, dict) and (item.get("id") or item.get("name"))]
            if not models:
                self._record_verification(row, "failed", "MODEL_LIST_INVALID", [])
                raise RemoteProviderError("Provider returned no usable models.")
            self._record_verification(row, "success", None, models)
            return {"ok": True, "models": models[:100], "protocol": row.protocol}
        except httpx.HTTPError as exc:
            self._record_verification(row, "failed", "ENDPOINT_UNREACHABLE", [])
            raise RemoteProviderError(f"Unable to reach provider: {exc}") from exc

    def _record_verification(
        self,
        row: RemoteProviderConfig,
        status: str,
        error_code: str | None,
        models: list[str],
    ) -> None:
        """Persist only non-sensitive provider verification metadata."""
        row.last_verified_at = datetime.datetime.utcnow()
        row.verification_status = status
        row.verification_error_code = error_code
        row.verified_models_json = json.dumps(models[:100], ensure_ascii=False)
        self.db.commit()

    def resolve(self, user_id: int, provider_id: int) -> dict:
        row = self.db.query(RemoteProviderConfig).filter(RemoteProviderConfig.user_id == user_id, RemoteProviderConfig.id == provider_id, RemoteProviderConfig.enabled.is_(True)).one_or_none()
        if row is None:
            raise RemoteProviderError("Provider not found or disabled.")
        return {"base_url": row.base_url, "protocol": row.protocol, "default_model": row.default_model, "api_key": self.cipher.decrypt(row.key_ciphertext)}

    def resolve_verified(self, user_id: int, provider_id: int, model_name: str) -> dict:
        """Resolve a ready remote target for internal runtime use only.

        This method never returns data through an API response; the decrypted key
        remains in the server-side provider adapter for the lifetime of one run.
        """
        row = (
            self.db.query(RemoteProviderConfig)
            .filter(
                RemoteProviderConfig.user_id == user_id,
                RemoteProviderConfig.id == provider_id,
                RemoteProviderConfig.enabled.is_(True),
                RemoteProviderConfig.verification_status == "success",
            )
            .one_or_none()
        )
        verified = self._models_from_json(row.verified_models_json) if row else []
        if row is None or not row.key_ciphertext or model_name not in verified:
            raise RemoteProviderError("The selected remote model target is no longer verified for this user.")
        return {
            "base_url": row.base_url,
            "protocol": row.protocol,
            "model": model_name,
            "api_key": self.cipher.decrypt(row.key_ciphertext),
        }

    @staticmethod
    def _models_from_json(value: str | None) -> list[str]:
        try:
            models = json.loads(value or "[]")
        except (TypeError, ValueError):
            return []
        return [str(model) for model in models if isinstance(model, str)] if isinstance(models, list) else []
