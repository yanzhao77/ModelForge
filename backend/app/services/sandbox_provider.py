"""Docker-backed sandbox diagnostics and guarded execution.

Execution is disabled by default. It only turns on when Docker is available,
``MODELFORGE_SANDBOX_EXECUTION=1`` is set, and the configured image already
exists locally. The provider never falls back to running code on the host.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from core.config import settings


class SandboxProviderError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(code)
        self.code = code
        self.message = message


class SandboxProviderService:
    def __init__(self, *, image: str | None = None, root: str | os.PathLike[str] | None = None):
        self.image = image or os.getenv("MODELFORGE_SANDBOX_IMAGE", "python:3.12-alpine")
        self.root = Path(root or settings.data_dir) / "sandbox-workspaces"

    def status(self) -> dict:
        docker = shutil.which("docker")
        if not docker:
            return _disabled("DOCKER_CLI_UNAVAILABLE", "Docker CLI was not found on PATH.")

        try:
            completed = subprocess.run(
                [docker, "info", "--format", "{{json .}}"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return _disabled("DOCKER_DAEMON_UNAVAILABLE", "Docker daemon did not answer the diagnostics request.", docker=docker)

        if completed.returncode != 0:
            return _disabled(
                "DOCKER_DAEMON_UNAVAILABLE",
                "Docker daemon is not available to this process.",
                docker=docker,
                detail=(completed.stderr or completed.stdout or "")[:500],
            )

        try:
            info = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError:
            info = {}
        security_options = info.get("SecurityOptions") if isinstance(info.get("SecurityOptions"), list) else []
        configured = os.getenv("MODELFORGE_SANDBOX_EXECUTION", "").strip().lower() in {"1", "true", "yes"}
        image_available = self._image_available(docker)
        execution_enabled = configured and image_available
        return {
            "provider": "docker",
            "available": True,
            "execution_enabled": execution_enabled,
            "disabled_reason": None if execution_enabled else ("SANDBOX_EXECUTION_DISABLED" if not configured else "SANDBOX_IMAGE_UNAVAILABLE"),
            "host_fallback": False,
            "docker_cli": docker,
            "image": self.image,
            "image_available": image_available,
            "server_version": info.get("ServerVersion"),
            "rootless": any("rootless" in str(item).lower() for item in security_options),
            "security_options": security_options,
            "network_default": "disabled",
            "requires_approval": True,
        }

    def execute_python(self, code: str, *, timeout_seconds: int = 10) -> dict:
        status = self.status()
        if not status.get("execution_enabled"):
            raise SandboxProviderError(str(status.get("disabled_reason") or "SANDBOX_UNAVAILABLE"), "Sandbox execution is not enabled.")
        docker = status.get("docker_cli")
        if not isinstance(docker, str) or not docker:
            raise SandboxProviderError("DOCKER_CLI_UNAVAILABLE", "Docker CLI was not found on PATH.")
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="run_", dir=self.root) as workspace:
            workspace_path = Path(workspace)
            (workspace_path / "main.py").write_text(code, encoding="utf-8")
            output_dir = workspace_path / "output"
            output_dir.mkdir()
            command = [
                docker,
                "run",
                "--rm",
                "--network",
                "none",
                "--cpus",
                "1",
                "--memory",
                "512m",
                "--pids-limit",
                "128",
                "--read-only",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=64m",
                "-v",
                f"{workspace_path}:/workspace:rw",
                "-w",
                "/workspace",
                self.image,
                "python",
                "/workspace/main.py",
            ]
            try:
                completed = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=max(1, min(timeout_seconds, 60)),
                )
            except subprocess.TimeoutExpired as exc:
                raise SandboxProviderError("SANDBOX_TIMEOUT", "Sandbox execution timed out.") from exc
            return {
                "provider": "docker",
                "image": self.image,
                "exit_code": completed.returncode,
                "stdout": (completed.stdout or "")[:20000],
                "stderr": (completed.stderr or "")[:20000],
                "output_files": _collect_output_files(output_dir),
                "network": "disabled",
                "host_fallback": False,
            }

    def _image_available(self, docker: str) -> bool:
        try:
            completed = subprocess.run(
                [docker, "image", "inspect", self.image],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return completed.returncode == 0


def _disabled(code: str, message: str, *, docker: str | None = None, detail: str | None = None) -> dict:
    payload = {
        "provider": "docker",
        "available": False,
        "execution_enabled": False,
        "disabled_reason": code,
        "message": message,
        "host_fallback": False,
        "network_default": "disabled",
        "requires_approval": True,
    }
    if docker:
        payload["docker_cli"] = docker
    if detail:
        payload["detail"] = detail
    return payload


def _collect_output_files(output_dir: Path) -> list[dict]:
    files: list[dict] = []
    root = output_dir.resolve()
    for path in sorted(root.rglob("*")):
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if root not in resolved.parents or not resolved.is_file() or path.is_symlink():
            continue
        stat = resolved.stat()
        if stat.st_size > 1024 * 1024:
            files.append({"path": str(resolved.relative_to(root)), "size_bytes": stat.st_size, "skipped": "OUTPUT_TOO_LARGE"})
            continue
        files.append({"path": str(resolved.relative_to(root)), "size_bytes": stat.st_size, "text_preview": resolved.read_text(encoding="utf-8", errors="replace")[:4000]})
    return files


__all__ = ["SandboxProviderError", "SandboxProviderService"]
