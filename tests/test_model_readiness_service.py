"""Unit tests for the credential-safe model readiness aggregation service."""

from __future__ import annotations

import json
import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = os.path.dirname(os.path.dirname(__file__))
APP = os.path.join(ROOT, "backend", "app")
if APP not in sys.path:
    sys.path.insert(0, APP)

from core.database import Base
from models.records import ModelRecord, RemoteProviderConfig, User
from services.model_readiness_service import ModelReadinessError, ModelReadinessService


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _user(db):
    user = User(username="readiness-user", password_hash="hash")
    db.add(user)
    db.commit()
    return user


def test_snapshot_requires_setup_without_models():
    db = _session()
    user = _user(db)

    snapshot = ModelReadinessService(db).snapshot(user.id)

    assert snapshot["level"] == "SETUP_REQUIRED"
    assert snapshot["recommended_action"] == "open_model_setup"
    assert snapshot["blocking_reasons"][0]["code"] == "NO_MODEL"


def test_available_local_model_is_ready_and_can_be_default():
    db = _session()
    user = _user(db)
    model = ModelRecord(user_id=user.id, name="local-gguf", status="available")
    db.add(model)
    db.commit()
    service = ModelReadinessService(db)

    before = service.snapshot(user.id)
    assert before["level"] == "READY"
    assert before["default_target"] is None
    after = service.set_default(user.id, kind="local", model_ref=str(model.id))

    assert after["default_target"]["model_name"] == "local-gguf"
    assert after["recommended_action"] == "open_chat"


def test_verified_remote_provider_is_ready_without_exposing_credentials():
    db = _session()
    user = _user(db)
    provider = RemoteProviderConfig(
        user_id=user.id,
        name="remote",
        base_url="https://api.example.test/v1",
        protocol="responses",
        default_model="example-chat",
        key_ciphertext="ciphertext-never-exposed",
        verification_status="success",
        verified_models_json=json.dumps(["example-chat", "another-model"]),
    )
    db.add(provider)
    db.commit()

    snapshot = ModelReadinessService(db).snapshot(user.id)

    assert snapshot["level"] == "READY"
    assert snapshot["targets"][0]["kind"] == "remote"
    assert "ciphertext" not in json.dumps(snapshot)
    assert "key" not in snapshot["targets"][0]


def test_unverified_provider_is_degraded_and_cannot_be_selected():
    db = _session()
    user = _user(db)
    provider = RemoteProviderConfig(
        user_id=user.id,
        name="remote",
        base_url="https://api.example.test/v1",
        protocol="responses",
        default_model="example-chat",
        key_ciphertext="ciphertext-never-exposed",
        verification_status="failed",
    )
    db.add(provider)
    db.commit()
    service = ModelReadinessService(db)

    snapshot = service.snapshot(user.id)
    assert snapshot["level"] == "DEGRADED"
    assert snapshot["recommended_action"] == "verify_provider"
    try:
        service.set_default(user.id, kind="remote", model_ref="example-chat", provider_id=provider.id)
    except ModelReadinessError:
        pass
    else:
        raise AssertionError("unverified provider must not be selectable")
