"""Safe GitHub Release update checks for the desktop client."""
from __future__ import annotations

import hashlib
import platform
import re
from dataclasses import dataclass
from pathlib import Path

import httpx


class UpdateError(RuntimeError):
    """A release payload or downloaded installer is not safe to use."""


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    notes: str
    published_at: str | None
    asset_name: str
    asset_url: str
    checksum_url: str


def _version_key(value: str) -> tuple[int, ...]:
    values = re.findall(r"\d+", value)
    return tuple(int(part) for part in values) or (0,)


class GitHubReleaseUpdater:
    """Fetch and verify checksum-protected release assets from GitHub."""

    def __init__(self, repository: str, current_version: str, update_dir: Path | None = None):
        self.repository = repository
        self.current_version = current_version
        self.update_dir = update_dir or Path.home() / "Library" / "Application Support" / "ModelForge" / "updates"

    @property
    def latest_url(self) -> str:
        return f"https://api.github.com/repos/{self.repository}/releases/latest"

    def check_latest(self) -> UpdateInfo | None:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "ModelForge-Desktop-Updater"}
        try:
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                response = client.get(self.latest_url, headers=headers)
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                release = response.json()
        except httpx.HTTPError as error:
            raise UpdateError(f"无法检查 GitHub Release：{error}") from error
        version = str(release.get("tag_name") or "").lstrip("v")
        if not version or _version_key(version) <= _version_key(self.current_version):
            return None
        asset, checksum = self._select_assets(release.get("assets") or [])
        if not asset or not checksum:
            raise UpdateError("最新 Release 缺少 macOS 安装包或 checksums.txt，已拒绝下载。")
        return UpdateInfo(
            version=version,
            notes=str(release.get("body") or "暂无发布说明。"),
            published_at=release.get("published_at"),
            asset_name=str(asset["name"]),
            asset_url=str(asset["browser_download_url"]),
            checksum_url=str(checksum["browser_download_url"]),
        )

    def _select_assets(self, assets: list[dict]) -> tuple[dict | None, dict | None]:
        if platform.system().lower() != "darwin":
            return None, None
        installers = [asset for asset in assets if str(asset.get("name", "")).lower().endswith((".dmg", ".zip"))]
        installer = next(
            (
                asset
                for asset in installers
                if "macos" in str(asset.get("name", "")).lower()
                or "darwin" in str(asset.get("name", "")).lower()
            ),
            None,
        )
        checksum = next(
            (
                asset
                for asset in assets
                if str(asset.get("name", "")).lower() in {"checksums.txt", "sha256sums.txt"}
            ),
            None,
        )
        return installer, checksum

    def download_and_verify(self, update: UpdateInfo) -> Path:
        self.update_dir.mkdir(parents=True, exist_ok=True)
        target = self.update_dir / update.asset_name
        headers = {"User-Agent": "ModelForge-Desktop-Updater"}
        try:
            with httpx.Client(
                timeout=httpx.Timeout(connect=15.0, read=120.0, write=120.0, pool=30.0),
                follow_redirects=True,
            ) as client:
                checksum_response = client.get(update.checksum_url, headers=headers)
                checksum_response.raise_for_status()
                expected = self._find_checksum(checksum_response.text, update.asset_name)
                if not expected:
                    raise UpdateError(f"checksums.txt 未包含 {update.asset_name}，已拒绝安装包。")
                with client.stream("GET", update.asset_url, headers=headers) as response:
                    response.raise_for_status()
                    digest = hashlib.sha256()
                    with target.open("wb") as handle:
                        for chunk in response.iter_bytes():
                            handle.write(chunk)
                            digest.update(chunk)
        except httpx.HTTPError as error:
            target.unlink(missing_ok=True)
            raise UpdateError(f"下载更新失败：{error}") from error
        actual = digest.hexdigest().lower()
        if actual != expected.lower():
            target.unlink(missing_ok=True)
            raise UpdateError("安装包 SHA-256 校验失败，文件已删除。")
        return target

    @staticmethod
    def _find_checksum(contents: str, asset_name: str) -> str | None:
        for line in contents.splitlines():
            parts = line.strip().split()
            if (
                len(parts) >= 2
                and parts[1].lstrip("*") == asset_name
                and re.fullmatch(r"[a-fA-F0-9]{64}", parts[0])
            ):
                return parts[0]
        return None
