"""Marketplace facade built on the package registry (V3.2)."""

from __future__ import annotations

from services.package_service import SUPPORTED_KINDS, PackageError, PackageService

RISKY_PERMISSION_PREFIXES = ("filesystem.", "process.", "network.", "credentials.", "payment.")
RISKY_TEXT = ("rm -rf", "curl ", "wget ", "private_key", "/etc/passwd", "..")


class MarketplaceService:
    """Search, inspect and install package-backed marketplace entries."""

    def __init__(self, db):
        self.db = db
        self.packages = PackageService(db)

    def search(self, user_id: int, *, query: str | None = None, kind: str | None = None) -> list[dict]:
        kind = kind.strip().lower() if kind else None
        rows = self.packages.list(user_id, kind=kind)
        needle = (query or "").strip().lower()
        if needle:
            rows = [row for row in rows if needle in " ".join(str(row.get(key) or "") for key in ("package_id", "name", "description", "kind")).lower()]
        return [self._entry(row) for row in rows]

    def detail(self, user_id: int, package_id: str, version: str | None = None) -> dict:
        document = self.packages.get(user_id, package_id, version)
        return {**self._entry(document), "payload": document.get("payload") or {}, "security_scan": self.scan_document(document)}

    def install(self, user_id: int, document: dict | None = None, *, package_id: str | None = None, version: str | None = None, conflict: str = "rename") -> dict:
        if document is None:
            if not package_id:
                raise PackageError("MARKETPLACE_PACKAGE_REQUIRED", "package_id or document is required.")
            stored = self.packages.get(user_id, package_id, version)
            document = {"schema_version": stored.get("manifest", {}).get("schema_version", 1), "manifest": stored.get("manifest") or {}, "payload": stored.get("payload") or {}}
        scan = self.scan_document(document)
        result = self.packages.import_document(user_id, document, conflict=conflict)
        return {**result, "security_scan": scan}

    def uninstall(self, user_id: int, package_id: str, version: str | None = None) -> dict:
        removed = self.packages.delete(user_id, package_id, version)
        if not removed:
            raise PackageError("PACKAGE_NOT_FOUND", "Package not found.", {"package_id": package_id}, http_status=404)
        return {"ok": True, "removed": removed}

    def scan_document(self, document: dict) -> dict:
        manifest = document.get("manifest") if isinstance(document, dict) else None
        payload = document.get("payload") if isinstance(document, dict) else None
        findings: list[dict] = []
        if not isinstance(manifest, dict) or not isinstance(payload, dict):
            findings.append({"severity": "HIGH", "code": "PACKAGE_SHAPE_INVALID", "message": "Package must include manifest and payload objects."})
            return {"status": "blocked", "findings": findings}
        kind = str(manifest.get("kind") or "").lower()
        if kind not in SUPPORTED_KINDS:
            findings.append({"severity": "HIGH", "code": "PACKAGE_KIND_UNSUPPORTED", "message": "Unsupported package kind."})
        for permission in manifest.get("permissions") or []:
            text = str(permission).lower()
            if text.startswith(RISKY_PERMISSION_PREFIXES):
                findings.append({"severity": "MEDIUM", "code": "PERMISSION_REVIEW_REQUIRED", "message": f"Permission requires review: {permission}"})
        serialized = str(document).lower()
        for marker in RISKY_TEXT:
            if marker in serialized:
                findings.append({"severity": "MEDIUM", "code": "SUSPICIOUS_PACKAGE_TEXT", "message": f"Suspicious text marker found: {marker}"})
        status = "blocked" if any(item["severity"] == "HIGH" for item in findings) else "review" if findings else "passed"
        return {"status": status, "findings": findings}

    def _entry(self, row: dict) -> dict:
        manifest = row.get("manifest") or {}
        return {
            "package_id": row.get("package_id"),
            "kind": row.get("kind"),
            "version": row.get("version"),
            "name": row.get("name"),
            "description": row.get("description"),
            "license": row.get("license"),
            "requires": manifest.get("requires") or [],
            "permissions": manifest.get("permissions") or manifest.get("tools") or [],
            "manifest": manifest,
            "created_at": row.get("created_at"),
        }


__all__ = ["MarketplaceService"]
