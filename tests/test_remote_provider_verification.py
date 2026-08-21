"""Verification summary persistence tests for remote model providers."""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = os.path.dirname(os.path.dirname(__file__))
APP = os.path.join(ROOT, "backend", "app")
if APP not in sys.path:
    sys.path.insert(0, APP)

from core.database import Base
from models.records import RemoteProviderConfig, User
from services.remote_provider_service import RemoteProviderError, RemoteProviderService


def _service():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    user = User(username="provider-verification", password_hash="hash")
    db.add(user)
    db.commit()
    provider = RemoteProviderConfig(
        user_id=user.id,
        name="Provider",
        base_url="https://api.example.test/v1",
        protocol="responses",
        default_model="verified-model",
        key_ciphertext="never-return-this",
    )
    db.add(provider)
    db.commit()
    service = RemoteProviderService(db, "/tmp")
    service.cipher = MagicMock()
    service.cipher.decrypt.return_value = "test-secret"
    return db, user, provider, service


def _client_with_response(status_code: int, payload: dict):
    response = MagicMock(status_code=status_code)
    response.json.return_value = payload
    client = MagicMock()
    client.__enter__.return_value = client
    client.get.return_value = response
    return client


def test_successful_verification_persists_only_non_sensitive_summary():
    db, user, provider, service = _service()
    client = _client_with_response(200, {"data": [{"id": "verified-model"}, {"id": "other"}]})

    with patch("services.remote_provider_service.httpx.Client", return_value=client):
        result = service.verify(user.id, provider.id)

    db.refresh(provider)
    assert result["models"] == ["verified-model", "other"]
    assert provider.verification_status == "success"
    assert provider.verification_error_code is None
    assert "test-secret" not in (provider.verified_models_json or "")
    assert "never-return-this" not in str(provider.to_public_dict())


def test_authentication_failure_is_persisted_as_recoverable_error_code():
    db, user, provider, service = _service()
    client = _client_with_response(401, {"error": {"message": "invalid key"}})

    with patch("services.remote_provider_service.httpx.Client", return_value=client):
        with pytest.raises(RemoteProviderError, match="HTTP 401"):
            service.verify(user.id, provider.id)

    db.refresh(provider)
    assert provider.verification_status == "failed"
    assert provider.verification_error_code == "AUTHENTICATION_FAILED"


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [(429, "RATE_LIMITED"), (503, "PROVIDER_HTTP_ERROR")],
)
def test_limit_and_service_failures_persist_safe_diagnostics(status_code, expected):
    db, user, provider, service = _service()
    client = _client_with_response(status_code, {"error": {"message": "upstream failure"}})

    with patch("services.remote_provider_service.httpx.Client", return_value=client):
        with pytest.raises(RemoteProviderError):
            service.verify(user.id, provider.id)

    db.refresh(provider)
    assert provider.verification_status == "failed"
    assert provider.verification_error_code == expected
    assert "test-secret" not in (provider.verified_models_json or "")
