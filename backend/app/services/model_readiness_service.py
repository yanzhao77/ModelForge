"""Read-only, credential-safe model readiness aggregation for desktop clients."""

from __future__ import annotations

import datetime
import json

from models.records import ModelRecord, RemoteProviderConfig, UserModelPreference
from sqlalchemy import or_
from sqlalchemy.orm import Session


class ModelReadinessError(ValueError):
    """Raised when a requested default target is not currently usable."""


class ModelReadinessService:
    """Build one user-scoped model availability snapshot without external I/O."""

    _READY_PROVIDER_STATUS = "success"

    def __init__(self, db: Session):
        self.db = db

    def snapshot(self, user_id: int) -> dict:
        targets = self._targets(user_id)
        preference = self.db.get(UserModelPreference, user_id)
        default_target = self._preferred_target(preference, targets)
        providers = self.db.query(RemoteProviderConfig).filter_by(user_id=user_id).all()

        if targets:
            level = "READY"
            action = "open_chat" if default_target else "select_default"
            reasons: list[dict] = []
        elif providers or self._has_unavailable_local_model(user_id):
            level = "DEGRADED"
            action, reasons = self._degraded_reason(providers, user_id)
        else:
            level = "SETUP_REQUIRED"
            action = "open_model_setup"
            reasons = [self._reason("NO_MODEL", "model_inventory", action, "readiness.no_model")]

        return {
            "schema_version": 1,
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "level": level,
            "targets": targets,
            "default_target": default_target,
            "blocking_reasons": reasons,
            "recommended_action": action,
        }

    def set_default(
        self,
        user_id: int,
        *,
        kind: str,
        model_ref: str,
        provider_id: int | None = None,
        commit: bool = True,
    ) -> dict:
        target = self._find_target(kind, model_ref, provider_id, self._targets(user_id))
        if target is None:
            raise ModelReadinessError("The selected model target is not ready for this user.")
        preference = self.db.get(UserModelPreference, user_id)
        if preference is None:
            preference = UserModelPreference(user_id=user_id)
            self.db.add(preference)
        preference.default_kind = target["kind"]
        preference.default_model_ref = target["model_ref"]
        preference.default_provider_id = target.get("provider_id")
        self.db.flush()
        if commit:
            self.db.commit()
        return self.snapshot(user_id)

    def clear_default(self, user_id: int, *, commit: bool = True) -> dict:
        preference = self.db.get(UserModelPreference, user_id)
        if preference is not None:
            self.db.delete(preference)
            self.db.flush()
            if commit:
                self.db.commit()
        return self.snapshot(user_id)

    def target_for(
        self,
        user_id: int,
        *,
        kind: str,
        model_ref: str,
        provider_id: int | None = None,
    ) -> dict | None:
        """Return one current ready target without performing external I/O."""
        return self._find_target(kind, model_ref, provider_id, self._targets(user_id))

    def _targets(self, user_id: int) -> list[dict]:
        local_models = (
            self.db.query(ModelRecord)
            .filter(ModelRecord.status == "available")
            .filter(or_(ModelRecord.user_id == user_id, ModelRecord.user_id.is_(None)))
            .order_by(ModelRecord.name)
            .all()
        )
        targets = [
            {
                "kind": "local",
                "model_ref": str(model.id),
                "model_name": model.name,
                "provider_id": None,
                "provider_name": None,
                "protocol": None,
            }
            for model in local_models
        ]
        providers = (
            self.db.query(RemoteProviderConfig)
            .filter_by(user_id=user_id, enabled=True, verification_status=self._READY_PROVIDER_STATUS)
            .order_by(RemoteProviderConfig.name)
            .all()
        )
        for provider in providers:
            verified = self._models_from_json(provider.verified_models_json)
            if provider.key_ciphertext and provider.default_model in verified:
                targets.append(
                    {
                        "kind": "remote",
                        "model_ref": provider.default_model,
                        "model_name": provider.default_model,
                        "provider_id": provider.id,
                        "provider_name": provider.name,
                        "protocol": provider.protocol,
                    }
                )
        return targets

    def _has_unavailable_local_model(self, user_id: int) -> bool:
        return (
            self.db.query(ModelRecord)
            .filter(or_(ModelRecord.user_id == user_id, ModelRecord.user_id.is_(None)))
            .filter(ModelRecord.status != "available")
            .count()
            > 0
        )

    def _degraded_reason(self, providers: list[RemoteProviderConfig], user_id: int) -> tuple[str, list[dict]]:
        if any(not provider.key_ciphertext for provider in providers):
            action = "configure_remote"
            return action, [self._reason("REMOTE_KEY_MISSING", "remote_provider", action, "readiness.remote_key_missing")]
        if any(provider.verification_status != self._READY_PROVIDER_STATUS for provider in providers):
            action = "verify_provider"
            return action, [self._reason("UNVERIFIED_PROVIDER", "remote_provider", action, "readiness.provider_unverified")]
        if self._has_unavailable_local_model(user_id):
            action = "scan_local"
            return action, [self._reason("LOCAL_MODEL_UNAVAILABLE", "model_inventory", action, "readiness.local_model_unavailable")]
        action = "open_model_setup"
        return action, [self._reason("NO_READY_TARGET", "model_inventory", action, "readiness.no_ready_target")]

    @staticmethod
    def _models_from_json(value: str | None) -> list[str]:
        try:
            parsed = json.loads(value or "[]")
        except (TypeError, ValueError):
            return []
        return [str(item) for item in parsed if isinstance(item, str)] if isinstance(parsed, list) else []

    @staticmethod
    def _reason(code: str, scope: str, action: str, message_key: str) -> dict:
        return {"code": code, "scope": scope, "action": action, "message_key": message_key}

    @staticmethod
    def _find_target(kind: str, model_ref: str, provider_id: int | None, targets: list[dict]) -> dict | None:
        for target in targets:
            if target["kind"] == kind and target["model_ref"] == model_ref and target.get("provider_id") == provider_id:
                return target
        return None

    @staticmethod
    def _preferred_target(preference: UserModelPreference | None, targets: list[dict]) -> dict | None:
        if preference is None:
            return None
        return ModelReadinessService._find_target(
            preference.default_kind,
            preference.default_model_ref,
            preference.default_provider_id,
            targets,
        )
