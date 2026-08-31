"""Comprehensive tests for services.downloader."""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from models.records import DownloadTaskRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(task_id: str = "aa" * 16, **overrides) -> MagicMock:
    """Return a mock DownloadTaskRecord with sensible defaults."""
    task = MagicMock(spec=DownloadTaskRecord)
    task.id = task_id
    task.user_id = overrides.get("user_id", 1)
    task.repo_id = overrides.get("repo_id", "owner/repo")
    task.filename = overrides.get("filename", None)
    task.status = overrides.get("status", "PENDING")
    task.progress = overrides.get("progress", 0)
    task.message = overrides.get("message", "Pending")
    task.error_code = overrides.get("error_code", None)
    task.completed_at = overrides.get("completed_at", None)
    return task


def _make_session(get_return=None, all_return=None):
    """Build a mock SQLAlchemy session usable as a context manager."""
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    session.get.return_value = get_return
    query = MagicMock()
    session.query.return_value = query
    query.filter_by.return_value = query
    query.order_by.return_value = query
    query.first.return_value = get_return
    query.all.return_value = all_return if all_return is not None else []
    return session


# ---------------------------------------------------------------------------
# start()
# ---------------------------------------------------------------------------

class TestStart:
    def test_start_uses_provided_db(self):
        from services.downloader import Downloader

        session = MagicMock()
        session.add = MagicMock()
        session.commit = MagicMock()
        session.refresh = MagicMock()

        dl = Downloader()
        with patch("services.downloader.SessionLocal") as mock_sl, \
             patch.object(dl, "_schedule"):
            result = dl.start("owner/model", user_id=1, db=session)
            mock_sl.assert_not_called()
            session.add.assert_called_once()
            session.commit.assert_called_once()
            session.refresh.assert_called_once()
            assert result is not None

    def test_start_creates_session_when_db_is_none(self):
        from services.downloader import Downloader

        session = MagicMock()
        session.add = MagicMock()
        session.commit = MagicMock()
        session.refresh = MagicMock()

        dl = Downloader()
        with patch("services.downloader.SessionLocal", return_value=session), \
             patch.object(dl, "_schedule"):
            result = dl.start("owner/model", user_id=1, db=None)
            session.close.assert_called_once()
            assert result is not None

    def test_start_passes_filename(self):
        from services.downloader import Downloader

        session = MagicMock()
        session.add = MagicMock()
        session.commit = MagicMock()
        session.refresh = MagicMock()

        dl = Downloader()
        with patch("services.downloader.SessionLocal", return_value=session), \
             patch.object(dl, "_schedule"):
            dl.start("owner/model", user_id=1, filename="model.gguf", db=session)
            created = session.add.call_args[0][0]
            assert created.filename == "model.gguf"

    def test_start_rollback_on_exception(self):
        from services.downloader import Downloader

        session = MagicMock()
        session.add = MagicMock()
        session.commit.side_effect = RuntimeError("boom")

        dl = Downloader()
        with patch("services.downloader.SessionLocal", return_value=session), \
             patch.object(dl, "_schedule"):
            with pytest.raises(RuntimeError):
                dl.start("owner/model", user_id=1)
            session.rollback.assert_called_once()

    def test_start_calls_schedule(self):
        from services.downloader import Downloader

        session = MagicMock()
        session.add = MagicMock()
        session.commit = MagicMock()
        session.refresh = MagicMock()

        dl = Downloader()
        with patch("services.downloader.SessionLocal", return_value=session), \
             patch.object(dl, "_schedule") as mock_sched:
            dl.start("owner/model", user_id=1, db=session)
            assert mock_sched.call_count == 1


# ---------------------------------------------------------------------------
# get()
# ---------------------------------------------------------------------------

class TestGet:
    def test_get_found_with_db(self):
        from services.downloader import Downloader

        task = _make_task()
        session = _make_session(get_return=task)

        dl = Downloader()
        result = dl.get("aa" * 16, user_id=1, db=session)
        assert result is task
        session.close.assert_not_called()

    def test_get_not_found_with_db(self):
        from services.downloader import Downloader

        session = _make_session(get_return=None)

        dl = Downloader()
        result = dl.get("zz" * 16, user_id=2, db=session)
        assert result is None

    def test_get_creates_session_when_db_none(self):
        from services.downloader import Downloader

        task = _make_task()
        session = _make_session(get_return=task)

        dl = Downloader()
        with patch("services.downloader.SessionLocal", return_value=session):
            result = dl.get("aa" * 16, user_id=1, db=None)
            assert result is not None
            session.close.assert_called_once()

    def test_get_passes_filter_by_args(self):
        from services.downloader import Downloader

        session = _make_session(get_return=_make_task())

        dl = Downloader()
        dl.get("aa" * 16, user_id=5, db=session)
        session.query.return_value.filter_by.assert_called_once_with(
            id="aa" * 16, user_id=5
        )


# ---------------------------------------------------------------------------
# list()
# ---------------------------------------------------------------------------

class TestList:
    def test_list_with_results(self):
        from services.downloader import Downloader

        t1 = _make_task(task_id="aa" * 16, user_id=1)
        t2 = _make_task(task_id="bb" * 16, user_id=1)
        session = _make_session(all_return=[t1, t2])

        dl = Downloader()
        results = dl.list(user_id=1, db=session)
        assert len(results) == 2
        assert results[0] is t1
        assert results[1] is t2

    def test_list_empty(self):
        from services.downloader import Downloader

        session = _make_session(all_return=[])

        dl = Downloader()
        results = dl.list(user_id=99, db=session)
        assert results == []

    def test_list_creates_session_when_db_none(self):
        from services.downloader import Downloader

        session = _make_session(all_return=[])

        dl = Downloader()
        with patch("services.downloader.SessionLocal", return_value=session):
            dl.list(user_id=1, db=None)
            session.close.assert_called_once()

    def test_list_orders_by_created_at_desc(self):
        from services.downloader import Downloader

        session = _make_session(all_return=[])

        dl = Downloader()
        dl.list(user_id=1, db=session)
        session.query.return_value.filter_by.return_value.order_by.assert_called_once()


# ---------------------------------------------------------------------------
# search_hf()
# ---------------------------------------------------------------------------

class TestSearchHF:
    @patch("services.hf_provider.HFProvider")
    def test_search_hf_no_author(self, mock_cls):
        from services.downloader import Downloader

        mock_cls.return_value.list_models.return_value = [
            {"name": "a", "author": "alice"},
            {"name": "b", "author": "bob"},
        ]

        dl = Downloader()
        results = dl.search_hf(query="gguf", author=None, limit=5)
        mock_cls.return_value.list_models.assert_called_once_with("gguf", limit=5)
        assert len(results) == 2

    @patch("services.hf_provider.HFProvider")
    def test_search_hf_with_author_filter(self, mock_cls):
        from services.downloader import Downloader

        mock_cls.return_value.list_models.return_value = [
            {"name": "a", "author": "Alice"},
            {"name": "b", "author": "Bob"},
            {"name": "c", "author": "alice"},
        ]

        dl = Downloader()
        results = dl.search_hf(query="llama", author="alice")
        assert len(results) == 2

    @patch("services.hf_provider.HFProvider")
    def test_search_hf_empty_query_defaults_to_gguf(self, mock_cls):
        from services.downloader import Downloader

        mock_cls.return_value.list_models.return_value = []

        dl = Downloader()
        dl.search_hf(query="", limit=10)
        mock_cls.return_value.list_models.assert_called_once_with("gguf", limit=10)

    @patch("services.hf_provider.HFProvider")
    def test_search_hf_no_author_match(self, mock_cls):
        from services.downloader import Downloader

        mock_cls.return_value.list_models.return_value = [
            {"name": "a", "author": "Bob"},
        ]

        dl = Downloader()
        results = dl.search_hf(query="x", author="alice")
        assert results == []

    @patch("services.hf_provider.HFProvider")
    def test_search_hf_author_case_insensitive(self, mock_cls):
        from services.downloader import Downloader

        mock_cls.return_value.list_models.return_value = [
            {"name": "a", "author": "ALICE"},
        ]

        dl = Downloader()
        results = dl.search_hf(query="x", author="alice")
        assert len(results) == 1

    @patch("services.hf_provider.HFProvider")
    def test_search_hf_missing_author_field(self, mock_cls):
        from services.downloader import Downloader

        mock_cls.return_value.list_models.return_value = [
            {"name": "a"},
        ]

        dl = Downloader()
        results = dl.search_hf(query="x", author="alice")
        assert results == []


# ---------------------------------------------------------------------------
# _set_state()
# ---------------------------------------------------------------------------

class TestSetState:
    def test_set_state_updates_task(self):
        from services.downloader import Downloader

        task = _make_task()
        session = _make_session(get_return=task)

        dl = Downloader()
        with patch("services.downloader.SessionLocal", return_value=session):
            result = dl._set_state("aa" * 16, status="RUNNING", progress=50, message="halfway")
            assert result is task
            assert task.status == "RUNNING"
            assert task.progress == 50
            assert task.message == "halfway"
            session.commit.assert_called_once()

    def test_set_state_truncates_long_message(self):
        from services.downloader import Downloader

        task = _make_task()
        session = _make_session(get_return=task)

        dl = Downloader()
        with patch("services.downloader.SessionLocal", return_value=session):
            dl._set_state("aa" * 16, status="FAILED", progress=0, message="x" * 300)
            assert task.message == "x" * 255

    def test_set_state_with_error_code(self):
        from services.downloader import Downloader

        task = _make_task()
        session = _make_session(get_return=task)

        dl = Downloader()
        with patch("services.downloader.SessionLocal", return_value=session):
            dl._set_state("aa" * 16, status="FAILED", progress=0,
                          message="err", error_code="MODEL_DOWNLOAD_FAILED")
            assert task.error_code == "MODEL_DOWNLOAD_FAILED"

    def test_set_state_sets_completed_at(self):
        from services.downloader import Downloader

        task = _make_task()
        session = _make_session(get_return=task)

        dl = Downloader()
        with patch("services.downloader.SessionLocal", return_value=session):
            dl._set_state("aa" * 16, status="COMPLETED", progress=100,
                          message="done", completed=True)
            assert task.completed_at is not None

    def test_set_state_no_completed_at_when_not_completed(self):
        from services.downloader import Downloader

        task = _make_task()
        session = _make_session(get_return=task)

        dl = Downloader()
        with patch("services.downloader.SessionLocal", return_value=session):
            dl._set_state("aa" * 16, status="RUNNING", progress=10,
                          message="running", completed=False)
            assert task.completed_at is None

    def test_set_state_no_task_returns_none(self):
        from services.downloader import Downloader

        session = _make_session(get_return=None)

        dl = Downloader()
        with patch("services.downloader.SessionLocal", return_value=session):
            result = dl._set_state("zz" * 16, status="RUNNING", progress=0, message="nope")
            assert result is None

    def test_set_state_refreshes_task(self):
        from services.downloader import Downloader

        task = _make_task()
        session = _make_session(get_return=task)

        dl = Downloader()
        with patch("services.downloader.SessionLocal", return_value=session):
            dl._set_state("aa" * 16, status="COMPLETED", progress=100, message="done")
            session.refresh.assert_called_once_with(task)


# ---------------------------------------------------------------------------
# _schedule()
# ---------------------------------------------------------------------------

class TestSchedule:
    def test_schedule_sync_path_no_event_loop(self):
        from services.downloader import Downloader

        dl = Downloader()
        with patch("asyncio.get_running_loop", side_effect=RuntimeError), \
             patch("services.downloader.threading.Thread") as mock_thread_cls:
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread
            dl._schedule("aa" * 16)
            mock_thread_cls.assert_called_once()
            assert mock_thread_cls.call_args.kwargs.get("daemon") is True
            mock_thread.start.assert_called_once()

    def test_schedule_async_path_with_event_loop(self):
        from services.downloader import Downloader

        dl = Downloader()
        mock_loop = MagicMock()
        with patch("asyncio.get_running_loop", return_value=mock_loop), \
             patch.object(dl, "_run", new_callable=AsyncMock):
            dl._schedule("aa" * 16)
            mock_loop.create_task.assert_called_once()


# ---------------------------------------------------------------------------
# _run()
# ---------------------------------------------------------------------------

@pytest.fixture()
def _mock_hf():
    """Inject a fake huggingface_hub into sys.modules for the duration of a test."""
    mock_hub = MagicMock()
    mock_hub.snapshot_download = MagicMock()
    old = sys.modules.get("huggingface_hub")
    sys.modules["huggingface_hub"] = mock_hub
    yield mock_hub
    if old is None:
        sys.modules.pop("huggingface_hub", None)
    else:
        sys.modules["huggingface_hub"] = old


class TestRun:
    @pytest.mark.asyncio
    async def test_run_task_not_found(self):
        from services.downloader import Downloader

        dl = Downloader()
        with patch.object(dl, "_set_state", return_value=None) as mock_set:
            await dl._run("aa" * 16)
            mock_set.assert_called_once()
            mock_set.assert_called_with(
                "aa" * 16, status="RUNNING", progress=0, message="Download started"
            )

    @pytest.mark.asyncio
    async def test_run_successful_download(self, _mock_hf):
        from services.downloader import Downloader

        task = _make_task()
        dl = Downloader()
        with patch.object(dl, "_set_state", return_value=task) as mock_set, \
             patch("services.downloader.settings") as mock_settings, \
             patch("services.downloader.Path") as mock_path_cls:
            mock_settings.hf_endpoint = None
            mock_settings.model_dir = "./models"
            mock_path = MagicMock()
            mock_path_cls.return_value.__truediv__ = MagicMock(return_value=mock_path)

            async def _fake_to_thread(func, *args, **kwargs):
                return func(*args, **kwargs)

            with patch("asyncio.to_thread", side_effect=_fake_to_thread):
                await dl._run("aa" * 16)

            statuses = [c.kwargs["status"] for c in mock_set.call_args_list]
            assert statuses == ["RUNNING", "RUNNING", "COMPLETED"]
            assert mock_set.call_args_list[-1].kwargs["completed"] is True

    @pytest.mark.asyncio
    async def test_run_failed_download(self, _mock_hf):
        from services.downloader import Downloader

        task = _make_task()
        dl = Downloader()
        with patch.object(dl, "_set_state", return_value=task) as mock_set, \
             patch("services.downloader.settings") as mock_settings, \
             patch("services.downloader.Path") as mock_path_cls:
            mock_settings.hf_endpoint = None
            mock_settings.model_dir = "./models"
            mock_path_cls.return_value.__truediv__ = MagicMock(return_value=MagicMock())

            with patch("asyncio.to_thread", side_effect=Exception("download error")):
                await dl._run("aa" * 16)

        last = mock_set.call_args_list[-1].kwargs
        assert last["status"] == "FAILED"
        assert last["error_code"] == "MODEL_DOWNLOAD_FAILED"
        assert last["completed"] is True
        assert last["message"] == "Download failed"

    @pytest.mark.asyncio
    async def test_run_sets_hf_endpoint_env(self, _mock_hf):
        from services.downloader import Downloader

        task = _make_task()
        dl = Downloader()
        with patch.object(dl, "_set_state", return_value=task) as mock_set, \
             patch("services.downloader.settings") as mock_settings, \
             patch("services.downloader.Path") as mock_path_cls:
            mock_settings.hf_endpoint = "https://my-mirror.com"
            mock_settings.model_dir = "./models"
            mock_path_cls.return_value.__truediv__ = MagicMock(return_value=MagicMock())

            async def _fake_to_thread(func, *args, **kwargs):
                return func(*args, **kwargs)

            with patch("asyncio.to_thread", side_effect=_fake_to_thread):
                await dl._run("aa" * 16)

        assert os.environ.get("HF_ENDPOINT") == "https://my-mirror.com"

    @pytest.mark.asyncio
    async def test_run_no_hf_endpoint_skips_env_set(self, _mock_hf):
        from services.downloader import Downloader

        task = _make_task()
        dl = Downloader()
        with patch.object(dl, "_set_state", return_value=task), \
             patch("services.downloader.settings") as mock_settings, \
             patch("services.downloader.Path") as mock_path_cls:
            mock_settings.hf_endpoint = None
            mock_settings.model_dir = "./models"
            mock_path_cls.return_value.__truediv__ = MagicMock(return_value=MagicMock())

            async def _fake_to_thread(func, *args, **kwargs):
                return func(*args, **kwargs)

            with patch("asyncio.to_thread", side_effect=_fake_to_thread):
                with patch("os.environ", {}) as mock_env:
                    await dl._run("aa" * 16)
                    assert "HF_ENDPOINT" not in mock_env

    @pytest.mark.asyncio
    async def test_run_passes_filename_as_allow_patterns(self, _mock_hf):
        from services.downloader import Downloader

        task = _make_task(filename="model.gguf")
        dl = Downloader()
        with patch.object(dl, "_set_state", return_value=task), \
             patch("services.downloader.settings") as mock_settings, \
             patch("services.downloader.Path") as mock_path_cls:
            mock_settings.hf_endpoint = None
            mock_settings.model_dir = "./models"
            mock_path_cls.return_value.__truediv__ = MagicMock(return_value=MagicMock())

            async def _fake_to_thread(func, *args, **kwargs):
                return func(*args, **kwargs)

            with patch("asyncio.to_thread", side_effect=_fake_to_thread) as mock_thread:
                await dl._run("aa" * 16)
                assert mock_thread.call_args.kwargs.get("allow_patterns") == ["model.gguf"]

    @pytest.mark.asyncio
    async def test_run_no_filename_no_allow_patterns(self, _mock_hf):
        from services.downloader import Downloader

        task = _make_task(filename=None)
        dl = Downloader()
        with patch.object(dl, "_set_state", return_value=task), \
             patch("services.downloader.settings") as mock_settings, \
             patch("services.downloader.Path") as mock_path_cls:
            mock_settings.hf_endpoint = None
            mock_settings.model_dir = "./models"
            mock_path_cls.return_value.__truediv__ = MagicMock(return_value=MagicMock())

            async def _fake_to_thread(func, *args, **kwargs):
                return func(*args, **kwargs)

            with patch("asyncio.to_thread", side_effect=_fake_to_thread) as mock_thread:
                await dl._run("aa" * 16)
                assert "allow_patterns" not in mock_thread.call_args.kwargs

    @pytest.mark.asyncio
    async def test_run_repo_id_slash_replaced(self, _mock_hf):
        from services.downloader import Downloader

        task = _make_task(repo_id="org/model-name")
        dl = Downloader()
        with patch.object(dl, "_set_state", return_value=task), \
             patch("services.downloader.settings") as mock_settings, \
             patch("services.downloader.Path") as mock_path_cls:
            mock_settings.hf_endpoint = None
            mock_settings.model_dir = "./models"
            div = mock_path_cls.return_value.__truediv__
            div.return_value = MagicMock()

            async def _fake_to_thread(func, *args, **kwargs):
                return func(*args, **kwargs)

            with patch("asyncio.to_thread", side_effect=_fake_to_thread):
                await dl._run("aa" * 16)
            div.assert_called_with("org_model-name")

    @pytest.mark.asyncio
    async def test_run_creates_target_directory(self, _mock_hf):
        from services.downloader import Downloader

        task = _make_task()
        dl = Downloader()
        mock_target = MagicMock()
        with patch.object(dl, "_set_state", return_value=task), \
             patch("services.downloader.settings") as mock_settings, \
             patch("services.downloader.Path") as mock_path_cls:
            mock_settings.hf_endpoint = None
            mock_settings.model_dir = "./models"
            mock_path_cls.return_value.__truediv__ = MagicMock(return_value=mock_target)

            async def _fake_to_thread(func, *args, **kwargs):
                return func(*args, **kwargs)

            with patch("asyncio.to_thread", side_effect=_fake_to_thread):
                await dl._run("aa" * 16)
            mock_target.mkdir.assert_called_once()
            assert mock_target.mkdir.call_args.kwargs.get("parents") is True
            assert mock_target.mkdir.call_args.kwargs.get("exist_ok") is True


# ---------------------------------------------------------------------------
# get_downloader() and module-level singleton
# ---------------------------------------------------------------------------

class TestGetDownloader:
    def test_get_downloader_returns_singleton(self):
        from services.downloader import get_downloader, downloader

        assert get_downloader() is downloader

    def test_downloader_is_downloader_class(self):
        from services.downloader import downloader, Downloader

        assert isinstance(downloader, Downloader)


# ---------------------------------------------------------------------------
# Downloader.__init__ – semaphore
# ---------------------------------------------------------------------------

class TestInit:
    def test_semaphore_created(self):
        from services.downloader import Downloader

        dl = Downloader()
        assert isinstance(dl._semaphore, asyncio.Semaphore)
        assert dl._semaphore._value == 2
