"""Resume, integrity, retry and cancellation coverage for services.downloader."""
from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from services.downloader import (  # noqa: E402
    DownloadCancelled,
    Downloader,
    DownloadFile,
    DownloadIntegrityError,
    DownloadPaused,
)

# ---------------------------------------------------------------------------
# HTTP doubles
# ---------------------------------------------------------------------------

def _status_error(status: int, url: str = "https://example.invalid/model.gguf") -> httpx.HTTPStatusError:
    request = httpx.Request("GET", url)
    return httpx.HTTPStatusError("upstream error", request=request, response=httpx.Response(status, request=request))


class _FakeResponse:
    def __init__(self, status_code: int = 200, chunks=(), error: Exception | None = None, headers=None):
        self.status_code = status_code
        self._chunks = list(chunks)
        self._error = error
        self.headers = dict(headers or {})

    def iter_bytes(self, chunk_size: int = 1024 * 1024):
        yield from self._chunks

    def raise_for_status(self) -> None:
        if self._error is not None:
            raise self._error


class _FakeStream:
    def __init__(self, response: _FakeResponse):
        self._response = response

    def __enter__(self) -> _FakeResponse:
        return self._response

    def __exit__(self, *_exc) -> bool:
        return False


class _FakeClient:
    """Minimal stand-in for ``httpx.Client`` streaming one response per call."""

    def __init__(self, responses, on_request=None):
        self._responses = list(responses)
        self._on_request = on_request
        self.requests: list[tuple[str, dict]] = []

    def stream(self, method: str, url: str, headers=None):
        self.requests.append((url, dict(headers or {})))
        if self._on_request is not None:
            self._on_request()
        if not self._responses:
            raise AssertionError("unexpected HTTP request")
        return _FakeStream(self._responses.pop(0))

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *_exc) -> bool:
        return False


def _downloader() -> Downloader:
    """A downloader with the DB-facing control plane stubbed out."""
    downloader = Downloader()
    downloader._set_state = lambda task_id, **kwargs: None
    downloader._control_status = lambda task_id: (None, None)
    return downloader


def _target(tmp_path):
    path = tmp_path / "owner_repo"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _spec(path="model.gguf", size=None, sha256=None, revision=None) -> DownloadFile:
    return DownloadFile(
        path=path,
        size=size,
        url=f"https://example.invalid/{path}",
        sha256=sha256,
        revision=revision,
    )


# ---------------------------------------------------------------------------
# Path containment
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["../escape.gguf", "nested/../../escape.gguf", "/etc/passwd", "", "   "])
def test_unsafe_repository_paths_are_rejected(tmp_path, path):
    with pytest.raises(DownloadIntegrityError):
        Downloader._safe_destination(tmp_path, path)


def test_repository_paths_stay_inside_the_model_directory(tmp_path):
    destination = Downloader._safe_destination(tmp_path, "sub/dir/model.gguf")
    assert destination == tmp_path.resolve() / "sub" / "dir" / "model.gguf"
    assert destination.is_relative_to(tmp_path.resolve())


# ---------------------------------------------------------------------------
# Resume behaviour
# ---------------------------------------------------------------------------

def test_download_resumes_from_existing_bytes(tmp_path):
    target = _target(tmp_path)
    (target / "model.gguf").write_bytes(b"abc")
    client = _FakeClient([_FakeResponse(206, [b"def"])])

    with patch("services.downloader.httpx.Client", return_value=client):
        _downloader()._download_files("task-1", [_spec(size=6)], target)

    assert (target / "model.gguf").read_bytes() == b"abcdef"
    assert client.requests[0][1] == {"Range": "bytes=3-"}


def test_download_restarts_when_upstream_ignores_range(tmp_path):
    target = _target(tmp_path)
    (target / "model.gguf").write_bytes(b"abc")
    client = _FakeClient([_FakeResponse(200, [b"abcdef"])])

    with patch("services.downloader.httpx.Client", return_value=client):
        _downloader()._download_files("task-1", [_spec(size=6)], target)

    assert (target / "model.gguf").read_bytes() == b"abcdef"
    assert client.requests[0][1] == {"Range": "bytes=3-"}


def test_download_restarts_when_upstream_resumes_at_a_wrong_offset(tmp_path):
    """A 206 that starts somewhere else must never be spliced onto our bytes."""
    target = _target(tmp_path)
    (target / "model.gguf").write_bytes(b"abc")
    downloader = _downloader()
    downloader._sleep_with_cancel = lambda task_id, seconds: None
    client = _FakeClient([
        _FakeResponse(206, [b"XY"], headers={"Content-Range": "bytes 1-2/6"}),
        _FakeResponse(200, [b"abcdef"]),
    ])

    with patch("services.downloader.httpx.Client", return_value=client):
        downloader._download_files("task-1", [_spec(size=6)], target)

    assert (target / "model.gguf").read_bytes() == b"abcdef"
    assert client.requests[0][1] == {"Range": "bytes=3-"}
    # The corrupt partial was dropped and the retry asked for the whole file.
    assert client.requests[1][1] == {}


def test_verified_file_is_never_requested_again(tmp_path):
    target = _target(tmp_path)
    (target / "model.gguf").write_bytes(b"abc")
    downloader = _downloader()
    downloader._write_manifest(
        target,
        {"files": {"model.gguf": {"size": 3, "sha256": None, "revision": None, "verified": True}}},
    )
    client = _FakeClient([])

    with patch("services.downloader.httpx.Client", return_value=client):
        downloader._download_files("task-1", [_spec(size=3)], target)

    assert client.requests == []


def test_full_length_file_without_manifest_entry_is_verified_once(tmp_path):
    target = _target(tmp_path)
    (target / "model.gguf").write_bytes(b"abc")
    digest = hashlib.sha256(b"abc").hexdigest()
    downloader = _downloader()
    client = _FakeClient([])

    with patch("services.downloader.httpx.Client", return_value=client):
        downloader._download_files("task-1", [_spec(size=3, sha256=digest)], target)

    assert client.requests == []
    assert (target / "model.gguf").read_bytes() == b"abc"
    manifest = downloader._load_manifest(target)
    assert manifest["files"]["model.gguf"]["verified"] is True


def test_corrupt_full_length_file_is_redownloaded_instead_of_failing(tmp_path):
    """Bytes that fail the hash check must be replaced within the same run."""
    target = _target(tmp_path)
    (target / "model.gguf").write_bytes(b"bad")
    digest = hashlib.sha256(b"abc").hexdigest()
    client = _FakeClient([_FakeResponse(200, [b"abc"])])

    with patch("services.downloader.httpx.Client", return_value=client):
        _downloader()._download_files("task-1", [_spec(size=3, sha256=digest)], target)

    assert (target / "model.gguf").read_bytes() == b"abc"
    # The corrupt file was discarded, not appended to with a Range request.
    assert client.requests[0][1] == {}


def test_partial_bytes_from_another_revision_are_not_spliced(tmp_path):
    target = _target(tmp_path)
    (target / "model.gguf").write_bytes(b"XXXXXX")
    downloader = _downloader()
    downloader._write_manifest(
        target,
        {"files": {"model.gguf": {"size": 6, "sha256": None, "revision": "old-rev", "verified": False}}},
    )
    client = _FakeClient([_FakeResponse(200, [b"abcdef"])])

    with patch("services.downloader.httpx.Client", return_value=client):
        downloader._download_files("task-1", [_spec(size=6, revision="new-rev")], target)

    assert (target / "model.gguf").read_bytes() == b"abcdef"
    assert client.requests[0][1] == {}


# ---------------------------------------------------------------------------
# Integrity verification
# ---------------------------------------------------------------------------

def test_sha256_mismatch_removes_the_file_and_fails(tmp_path):
    target = _target(tmp_path)
    client = _FakeClient([_FakeResponse(200, [b"abc"])])

    with patch("services.downloader.httpx.Client", return_value=client):
        with pytest.raises(DownloadIntegrityError):
            _downloader()._download_files("task-1", [_spec(size=3, sha256="0" * 64)], target)

    assert not (target / "model.gguf").exists()


def test_short_file_is_not_accepted_as_complete(tmp_path):
    target = _target(tmp_path)
    client = _FakeClient([_FakeResponse(200, [b"ab"])])

    with patch("services.downloader.httpx.Client", return_value=client):
        with pytest.raises(DownloadIntegrityError):
            _downloader()._download_files("task-1", [_spec(size=3)], target)

    assert not (target / "model.gguf").exists()


# ---------------------------------------------------------------------------
# Transient failure handling
# ---------------------------------------------------------------------------

def test_transient_upstream_error_is_retried(tmp_path):
    target = _target(tmp_path)
    downloader = _downloader()
    downloader._sleep_with_cancel = lambda task_id, seconds: None
    client = _FakeClient([_FakeResponse(503, error=_status_error(503)), _FakeResponse(200, [b"abc"])])

    with patch("services.downloader.httpx.Client", return_value=client):
        downloader._download_files("task-1", [_spec(size=3)], target)

    assert (target / "model.gguf").read_bytes() == b"abc"
    assert len(client.requests) == 2


def test_client_error_is_not_retried(tmp_path):
    target = _target(tmp_path)
    downloader = _downloader()
    downloader._sleep_with_cancel = lambda task_id, seconds: None
    client = _FakeClient([_FakeResponse(404, error=_status_error(404))])

    with patch("services.downloader.httpx.Client", return_value=client):
        with pytest.raises(httpx.HTTPStatusError):
            downloader._download_files("task-1", [_spec(size=3)], target)

    assert len(client.requests) == 1


# ---------------------------------------------------------------------------
# Cancellation and restart
# ---------------------------------------------------------------------------

def test_cancelled_task_stops_before_the_next_chunk(tmp_path):
    target = _target(tmp_path)
    downloader = _downloader()
    event = threading.Event()
    downloader._cancels["task-1"] = event
    client = _FakeClient([_FakeResponse(200, [b"a", b"b"])], on_request=event.set)

    with patch("services.downloader.httpx.Client", return_value=client):
        with pytest.raises(DownloadCancelled):
            downloader._download_files("task-1", [_spec()], target)


def test_paused_task_stops_the_worker_instead_of_waiting(tmp_path):
    """Pausing must release the global download slot, not block inside it."""
    target = _target(tmp_path)
    (target / "model.gguf").write_bytes(b"abc")
    downloader = _downloader()
    downloader._control_status = lambda task_id: ("PAUSED", None)
    client = _FakeClient([_FakeResponse(200, [b"abcdef"])])

    with patch("services.downloader.httpx.Client", return_value=client):
        with pytest.raises(DownloadPaused):
            downloader._download_files("task-1", [_spec(size=6)], target)

    # The bytes already on disk stay untouched so resume() can continue.
    assert (target / "model.gguf").read_bytes() == b"abc"


@pytest.mark.asyncio
async def test_paused_download_releases_its_download_slot(tmp_path):
    target = _target(tmp_path)
    downloader = Downloader(max_downloads=1)
    downloader._set_state = lambda task_id, **kwargs: SimpleNamespace(
        progress=0, repo_id="owner/repo", filename=None, user_id=7
    )
    downloader._control_status = lambda task_id: ("PAUSED", None)
    downloader._resolve_files = lambda repo_id, filename=None: [_spec(size=6)]
    downloader._target_path = lambda repo_id: target
    downloader._register_worker("task-1")
    client = _FakeClient([_FakeResponse(200, [b"abcdef"])])

    with patch("services.downloader.httpx.Client", return_value=client):
        await asyncio.wait_for(downloader._run("task-1"), timeout=15)

    assert downloader._semaphore.acquire(blocking=False) is True
    downloader._semaphore.release()


def test_restart_keeps_shared_files_and_reverifies_them(tmp_path, monkeypatch):
    """The model directory is shared, so restart must re-verify, never delete."""
    downloader = Downloader()
    target = _target(tmp_path)
    (target / "model.gguf").write_bytes(b"partial")
    downloader._write_manifest(
        target,
        {"files": {"model.gguf": {"size": 7, "sha256": None, "revision": "rev-1", "verified": True}}},
    )
    monkeypatch.setattr(downloader, "_target_path", lambda repo_id: target)
    monkeypatch.setattr(
        downloader,
        "get",
        lambda task_id, user_id, db=None: SimpleNamespace(repo_id="owner/repo", filename="model.gguf", progress=42),
    )
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        downloader, "_set_state", lambda task_id, **kwargs: calls.append((task_id, kwargs)) or None
    )
    monkeypatch.setattr(downloader, "start", lambda repo_id, user_id, filename=None, db=None: "new-task")

    observed: list[bool] = []
    exit_flag = downloader._register_worker("task-1")

    def worker() -> None:
        exit_flag.wait(5)
        observed.append(target.exists())
        with downloader._active_lock:
            downloader._active.discard("task-1")

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    result = downloader.restart("task-1", 7)
    thread.join(5)

    assert exit_flag.is_set()
    assert observed == [True]
    assert (target / "model.gguf").read_bytes() == b"partial"
    assert downloader._load_manifest(target)["files"]["model.gguf"]["verified"] is False
    assert result == "new-task"
    assert [kwargs["status"] for _task_id, kwargs in calls] == ["CANCELLED"]
    assert calls[0][1]["progress"] == 42


def test_restart_keeps_files_when_the_worker_does_not_stop(tmp_path, monkeypatch):
    downloader = Downloader()
    target = _target(tmp_path)
    (target / "model.gguf").write_bytes(b"partial")
    monkeypatch.setattr(downloader, "_target_path", lambda repo_id: target)
    monkeypatch.setattr(
        downloader,
        "get",
        lambda task_id, user_id, db=None: SimpleNamespace(repo_id="owner/repo", filename="model.gguf", progress=9),
    )
    monkeypatch.setattr(downloader, "_set_state", lambda task_id, **kwargs: None)
    monkeypatch.setattr(downloader, "_stop_worker", lambda task_id, timeout=15.0: False)
    monkeypatch.setattr(downloader, "start", lambda repo_id, user_id, filename=None, db=None: "new-task")

    assert downloader.restart("task-1", 7) == "new-task"
    assert (target / "model.gguf").read_bytes() == b"partial"


# ---------------------------------------------------------------------------
# Shared model directory
# ---------------------------------------------------------------------------

def test_same_target_downloads_are_serialized(tmp_path):
    """Two tasks resolving one repository must never write it concurrently."""
    target = _target(tmp_path)
    downloader = _downloader()
    order: list[str] = []
    order_lock = threading.Lock()

    def instrumented(task_id, files, target_dir):
        with order_lock:
            order.append(f"enter-{task_id}")
        time.sleep(0.2)
        with order_lock:
            order.append(f"exit-{task_id}")

    downloader._download_files_locked = instrumented
    threads = [
        threading.Thread(target=lambda task_id=task_id: downloader._download_files(task_id, [], target))
        for task_id in ("task-1", "task-2")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)

    assert order in (
        ["enter-task-1", "exit-task-1", "enter-task-2", "exit-task-2"],
        ["enter-task-2", "exit-task-2", "enter-task-1", "exit-task-1"],
    )


def test_manifest_write_is_atomic(tmp_path):
    target = _target(tmp_path)
    downloader = _downloader()
    temporary = target / (Downloader.MANIFEST_NAME + ".tmp")
    temporary.write_text("{ not json", encoding="utf-8")

    downloader._write_manifest(target, {"files": {}})

    assert not temporary.exists()
    assert downloader._load_manifest(target) == {"files": {}}


# ---------------------------------------------------------------------------
# Remote metadata
# ---------------------------------------------------------------------------

def _install_fake_hub(monkeypatch, info, url="https://hf-mirror.com/org/repo/resolve/main/model.gguf"):
    module = MagicMock()
    module.HfApi.return_value.model_info.return_value = info
    module.hf_hub_url.return_value = url
    monkeypatch.setitem(sys.modules, "huggingface_hub", module)
    return module


def test_resolve_files_carries_lfs_hash_and_revision(monkeypatch):
    sibling = SimpleNamespace(rfilename="model.gguf", size=123, lfs=SimpleNamespace(sha256="a" * 64))
    info = SimpleNamespace(siblings=[sibling], sha="rev-1")
    with patch("services.downloader.settings") as settings:
        settings.hf_endpoint = None
        _install_fake_hub(monkeypatch, info)
        files = Downloader()._resolve_files("org/repo")

    assert files[0].sha256 == "a" * 64
    assert files[0].revision == "rev-1"
    assert files[0].size == 123


def test_resolve_files_ignores_the_local_manifest(monkeypatch):
    siblings = [
        SimpleNamespace(rfilename=Downloader.MANIFEST_NAME, size=10, lfs=None),
        SimpleNamespace(rfilename="model.gguf", size=10, lfs=None),
    ]
    with patch("services.downloader.settings") as settings:
        settings.hf_endpoint = None
        _install_fake_hub(monkeypatch, SimpleNamespace(siblings=siblings, sha="rev-1"))
        files = Downloader()._resolve_files("org/repo")

    assert [item.path for item in files] == ["model.gguf"]


# ---------------------------------------------------------------------------
# Whole-run wiring
# ---------------------------------------------------------------------------

def test_run_sync_downloads_verifies_and_completes(tmp_path):
    import services.downloader as module

    target = tmp_path / "owner_repo"
    payload = b"gguf-bytes"
    digest = hashlib.sha256(payload).hexdigest()
    record = SimpleNamespace(
        id="task-1", user_id=7, repo_id="owner/repo", filename=None, status="PENDING", progress=0
    )
    states: list[dict] = []
    downloader = Downloader()
    downloader._set_state = lambda task_id, **kwargs: states.append(kwargs) or record
    downloader._control_status = lambda task_id: ("RUNNING", "RUNNING")
    downloader._resolve_files = lambda repo_id, filename=None: [
        DownloadFile("model.gguf", len(payload), "https://example.invalid/model.gguf", sha256=digest, revision="rev-1")
    ]
    downloader._target_path = lambda repo_id: target
    client = _FakeClient([_FakeResponse(200, [payload])])

    with patch("services.downloader.httpx.Client", return_value=client), \
         patch.object(module.settings, "hf_endpoint", None), \
         patch.object(module.settings, "model_dir", str(tmp_path)):
        downloader._run_sync("task-1")

    assert (target / "model.gguf").read_bytes() == payload
    assert states[0]["status"] == "RUNNING"
    assert states[-1]["status"] == "COMPLETED"
    assert states[-1]["progress"] == 100
    assert states[-1]["completed"] is True
    manifest = downloader._load_manifest(target)
    assert manifest["files"]["model.gguf"] == {
        "size": len(payload),
        "sha256": digest,
        "revision": "rev-1",
        "verified": True,
    }
