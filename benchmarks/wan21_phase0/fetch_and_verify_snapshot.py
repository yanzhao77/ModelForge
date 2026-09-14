"""Fetch and verify the pinned Wan2.1 T2V 1.3B snapshot for Phase 0.

This downloader is intentionally benchmark-local. It works around unstable Xet
snapshot reconstruction by downloading large files through HTTPS Range requests
and verifying the Hugging Face LFS SHA-256 etag before publishing each file.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx
from huggingface_hub import hf_hub_url, list_repo_files
from huggingface_hub.file_download import get_hf_file_metadata


REPO_ID = "Wan-AI/Wan2.1-T2V-1.3B-Diffusers"
REVISION = "0fad780a534b6463e45facd96134c9f345acfa5b"


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value.lower())


@dataclass(frozen=True)
class FileSpec:
    path: str
    size: int
    etag: str
    sha256_expected: str | None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest() -> list[FileSpec]:
    files = list_repo_files(REPO_ID, revision=REVISION)
    specs: list[FileSpec] = []
    for rel in files:
        meta = get_hf_file_metadata(hf_hub_url(REPO_ID, rel, revision=REVISION))
        if meta.size is None or meta.etag is None:
            raise RuntimeError(f"missing remote metadata for {rel}")
        etag = str(meta.etag).strip('"')
        specs.append(
            FileSpec(
                path=rel,
                size=int(meta.size),
                etag=etag,
                sha256_expected=etag if _is_sha256(etag) else None,
            )
        )
    return specs


def load_manifest(path: Path) -> list[FileSpec]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("repo_id") != REPO_ID or payload.get("revision") != REVISION:
        raise RuntimeError("saved manifest does not match the pinned Wan2.1 repository revision")
    return [FileSpec(**item) for item in payload.get("files", [])]


def verify_file(path: Path, spec: FileSpec) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing"
    size = path.stat().st_size
    if size != spec.size:
        return False, f"size {size} != {spec.size}"
    if spec.sha256_expected:
        actual = sha256_file(path)
        if actual != spec.sha256_expected:
            return False, f"sha256 {actual} != {spec.sha256_expected}"
    return True, "ok"


def get_url(relpath: str) -> str:
    return hf_hub_url(REPO_ID, relpath, revision=REVISION)


def download_small_file(spec: FileSpec, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60.0, read=120.0)) as client:
        response = client.get(get_url(spec.path))
        response.raise_for_status()
        tmp.write_bytes(response.content)
    ok, reason = verify_file(tmp, spec)
    if not ok:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"downloaded {spec.path} failed verification: {reason}")
    os.replace(tmp, target)


def _download_chunk(args: tuple[str, int, int, Path, int]) -> dict[str, Any]:
    relpath, start, end, chunk_path, attempt_count = args
    expected = end - start + 1
    if chunk_path.exists() and chunk_path.stat().st_size == expected:
        return {"start": start, "bytes": expected, "cached": True}
    headers = {"Range": f"bytes={start}-{end}"}
    last_error = None
    for attempt in range(1, attempt_count + 1):
        try:
            with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30.0, read=180.0)) as client:
                response = client.get(get_url(relpath), headers=headers)
                if response.status_code != 206:
                    raise RuntimeError(f"expected 206, got {response.status_code}")
                data = response.content
            if len(data) != expected:
                raise RuntimeError(f"chunk size {len(data)} != {expected}")
            chunk_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = chunk_path.with_name(chunk_path.name + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, chunk_path)
            return {"start": start, "bytes": expected, "cached": False, "attempt": attempt}
        except Exception as exc:  # retry boundary includes proxy/CDN resets
            last_error = exc
            time.sleep(min(10, attempt * 2))
    raise RuntimeError(f"failed chunk {start}-{end} for {relpath}: {last_error}")


def download_large_file(spec: FileSpec, target: Path, *, chunk_size: int, workers: int, retries: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    chunks_dir = target.with_name(target.name + ".chunks")
    chunks_dir.mkdir(parents=True, exist_ok=True)
    total_chunks = math.ceil(spec.size / chunk_size)
    jobs = []
    for index in range(total_chunks):
        start = index * chunk_size
        end = min(spec.size - 1, start + chunk_size - 1)
        jobs.append((spec.path, start, end, chunks_dir / f"{index:05d}.chunk", retries))
    print(f"downloading {spec.path}: {spec.size} bytes in {total_chunks} chunks", flush=True)
    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_download_chunk, job) for job in jobs]
        for future in concurrent.futures.as_completed(futures):
            future.result()
            completed += 1
            if completed % 5 == 0 or completed == total_chunks:
                print(f"  {completed}/{total_chunks} chunks", flush=True)
    tmp = target.with_name(target.name + ".tmp")
    with tmp.open("wb") as output:
        for index in range(total_chunks):
            chunk = chunks_dir / f"{index:05d}.chunk"
            with chunk.open("rb") as handle:
                shutil.copyfileobj(handle, output)
    ok, reason = verify_file(tmp, spec)
    if not ok:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"assembled {spec.path} failed verification: {reason}")
    os.replace(tmp, target)
    shutil.rmtree(chunks_dir, ignore_errors=True)


def fetch_and_verify(args: argparse.Namespace) -> int:
    root = Path(args.snapshot).resolve()
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root.parent / "snapshot_integrity_manifest.json"
    if args.verify_only:
        if not manifest_path.exists():
            raise RuntimeError(f"verify-only requires an existing manifest: {manifest_path}")
        specs = load_manifest(manifest_path)
    else:
        specs = build_manifest()
        manifest_path.write_text(
            json.dumps({"repo_id": REPO_ID, "revision": REVISION, "files": [asdict(spec) for spec in specs]}, indent=2),
            encoding="utf-8",
        )

    failures: list[dict[str, str]] = []
    for spec in specs:
        target = root / spec.path
        ok, reason = verify_file(target, spec)
        if ok:
            continue
        if args.verify_only:
            failures.append({"path": spec.path, "reason": reason})
            continue
        partial = target.with_name(target.name + ".partial")
        if partial.exists() and not target.exists():
            print(f"ignoring partial file for {spec.path}: {partial.stat().st_size} bytes", flush=True)
        try:
            if spec.sha256_expected:
                download_large_file(
                    spec,
                    target,
                    chunk_size=args.chunk_size_mb * 1024 * 1024,
                    workers=args.workers,
                    retries=args.retries,
                )
            else:
                print(f"downloading {spec.path}", flush=True)
                download_small_file(spec, target)
        except Exception as exc:
            failures.append({"path": spec.path, "reason": str(exc)})
            if args.fail_fast:
                break

    verification = []
    for spec in specs:
        ok, reason = verify_file(root / spec.path, spec)
        verification.append({"path": spec.path, "ok": ok, "reason": reason})
    result = {
        "repo_id": REPO_ID,
        "revision": REVISION,
        "snapshot": str(root),
        "mode": "verify-only" if args.verify_only else "fetch-and-verify",
        "complete": all(item["ok"] for item in verification),
        "failures": failures,
        "verification": verification,
    }
    result_path = root.parent / "snapshot_integrity_result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"complete": result["complete"], "result": str(result_path), "failures": failures[:3]}, ensure_ascii=False, indent=2))
    return 0 if result["complete"] else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", default="benchmarks/wan21_phase0/output/snapshot")
    parser.add_argument("--chunk-size-mb", type=int, default=32)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(fetch_and_verify(parse_args()))
