"""Unit tests for the persistent schedule service."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

ROOT = os.path.dirname(os.path.dirname(__file__))
APP = os.path.join(ROOT, "backend", "app")
if APP not in sys.path:
    sys.path.insert(0, APP)

from sqlalchemy.exc import IntegrityError

from models.records import ScheduledJob, ScheduleExecution
from services.schedule_service import ScheduleService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_job(**overrides) -> ScheduledJob:
    job = MagicMock(spec=ScheduledJob)
    job.id = overrides.get("id", "job_abc123")
    job.user_id = overrides.get("user_id", 1)
    job.name = overrides.get("name", "test-schedule")
    job.enabled = overrides.get("enabled", False)
    job.schedule_kind = overrides.get("schedule_kind", "once")
    job.delay_seconds = overrides.get("delay_seconds", 300.0)
    job.interval_seconds = overrides.get("interval_seconds", None)
    job.timezone = overrides.get("timezone", "UTC")
    job.schedule_config = overrides.get("schedule_config", "{}")
    job.misfire_policy = overrides.get("misfire_policy", "skip")
    job.run_spec = overrides.get("run_spec", "{}")
    job.concurrency_policy = overrides.get("concurrency_policy", "skip")
    job.max_failures = overrides.get("max_failures", 3)
    job.failure_count = overrides.get("failure_count", 0)
    job.runtime_job_id = overrides.get("runtime_job_id", None)
    job.pending_trigger = overrides.get("pending_trigger", False)
    job.next_run_at = overrides.get("next_run_at", datetime(2026, 1, 1, 12, 0))
    job.last_run_at = overrides.get("last_run_at", None)
    job.created_at = overrides.get("created_at", datetime(2026, 1, 1))
    return job


def _make_claim(**overrides) -> ScheduleExecution:
    claim = MagicMock(spec=ScheduleExecution)
    claim.id = overrides.get("id", "exec_001")
    claim.schedule_id = overrides.get("schedule_id", "job_abc123")
    claim.user_id = overrides.get("user_id", 1)
    claim.agent_run_id = overrides.get("agent_run_id", None)
    claim.trigger_kind = overrides.get("trigger_kind", "schedule")
    claim.occurrence_key = overrides.get("occurrence_key", "schedule:job_abc123:2026-01-01T12:00:00")
    claim.claim_token = overrides.get("claim_token", None)
    claim.claim_expires_at = overrides.get("claim_expires_at", None)
    claim.state_version = overrides.get("state_version", 1)
    claim.attempt_count = overrides.get("attempt_count", 0)
    claim.outcome = overrides.get("outcome", "triggered")
    claim.error_code = overrides.get("error_code", None)
    claim.error_message = overrides.get("error_message", None)
    claim.triggered_at = overrides.get("triggered_at", datetime(2026, 1, 1))
    claim.finished_at = overrides.get("finished_at", None)
    return claim


def _svc(db=None):
    db = db or MagicMock()
    return ScheduleService(db)


# ===================================================================
# _timezone
# ===================================================================

class TestTimezone:
    def test_default_utc(self):
        result = ScheduleService._timezone(None)
        assert str(result) == "UTC"

    def test_empty_string_falls_back_to_utc(self):
        result = ScheduleService._timezone("")
        assert str(result) == "UTC"

    def test_valid_timezone(self):
        result = ScheduleService._timezone("America/New_York")
        assert str(result) == "America/New_York"

    def test_invalid_timezone_raises(self):
        with pytest.raises(ValueError, match="timezone must be a valid IANA timezone"):
            ScheduleService._timezone("Not/A/Timezone")


# ===================================================================
# _validate
# ===================================================================

class TestValidate:
    def test_valid_once(self):
        ScheduleService._validate("once", 10.0, None, "UTC", {})

    def test_invalid_kind(self):
        with pytest.raises(ValueError, match="schedule_kind must be"):
            ScheduleService._validate("yearly", 10.0, None, "UTC", {})

    def test_once_requires_positive_delay(self):
        with pytest.raises(ValueError, match="positive delay_seconds"):
            ScheduleService._validate("once", None, None, "UTC", {})
        with pytest.raises(ValueError, match="positive delay_seconds"):
            ScheduleService._validate("once", -1, None, "UTC", {})

    def test_interval_requires_60_plus(self):
        with pytest.raises(ValueError, match="interval_seconds >= 60"):
            ScheduleService._validate("interval", None, 30, "UTC", {})
        with pytest.raises(ValueError, match="interval_seconds >= 60"):
            ScheduleService._validate("interval", None, None, "UTC", {})

    def test_daily_requires_time_of_day(self):
        with pytest.raises(ValueError, match="time_of_day in HH:MM"):
            ScheduleService._validate("daily", None, None, "UTC", {})

    def test_daily_bad_time_format(self):
        with pytest.raises(ValueError, match="time_of_day in HH:MM"):
            ScheduleService._validate("daily", None, None, "UTC", {"time_of_day": "not-a-time"})

    def test_daily_invalid_hour(self):
        with pytest.raises(ValueError, match="HH:MM 24-hour"):
            ScheduleService._validate("daily", None, None, "UTC", {"time_of_day": "25:00"})

    def test_daily_invalid_minute(self):
        with pytest.raises(ValueError, match="HH:MM 24-hour"):
            ScheduleService._validate("daily", None, None, "UTC", {"time_of_day": "12:61"})

    def test_daily_valid(self):
        ScheduleService._validate("daily", None, None, "UTC", {"time_of_day": "09:30"})

    def test_weekly_requires_time_of_day(self):
        with pytest.raises(ValueError, match="time_of_day in HH:MM"):
            ScheduleService._validate("weekly", None, None, "UTC", {})

    def test_weekly_requires_day_of_week(self):
        with pytest.raises(ValueError, match="day_of_week from 0"):
            ScheduleService._validate("weekly", None, None, "UTC", {"time_of_day": "09:00", "day_of_week": 7})

    def test_weekly_invalid_day_of_week_negative(self):
        with pytest.raises(ValueError, match="day_of_week from 0"):
            ScheduleService._validate("weekly", None, None, "UTC", {"time_of_day": "09:00", "day_of_week": -1})

    def test_weekly_valid(self):
        ScheduleService._validate("weekly", None, None, "UTC", {"time_of_day": "09:00", "day_of_week": 0})

    def test_invalid_timezone_in_validate(self):
        with pytest.raises(ValueError, match="timezone must be"):
            ScheduleService._validate("once", 10.0, None, "Invalid/Zone", {})


class TestValidatePayload:
    def test_invalid_concurrency_policy(self):
        svc = _svc()
        payload = {
            "agent_id": "a1",
            "schedule_kind": "once",
            "delay_seconds": 10,
            "concurrency_policy": "bogus",
        }
        with pytest.raises(ValueError, match="concurrency_policy must be"):
            svc._validate_payload(payload)

    def test_invalid_misfire_policy(self):
        svc = _svc()
        payload = {
            "agent_id": "a1",
            "schedule_kind": "once",
            "delay_seconds": 10,
            "misfire_policy": "bogus",
        }
        with pytest.raises(ValueError, match="misfire_policy must be"):
            svc._validate_payload(payload)


# ===================================================================
# _config
# ===================================================================

class TestConfig:
    def test_empty(self):
        assert ScheduleService._config({}) == {}

    def test_merges_schedule_config(self):
        prior = {"a": 1}
        result = ScheduleService._config({"schedule_config": {"b": 2}}, prior)
        assert result == {"a": 1, "b": 2}

    def test_top_level_time_of_day(self):
        result = ScheduleService._config({"time_of_day": "08:00"})
        assert result == {"time_of_day": "08:00"}

    def test_top_level_day_of_week(self):
        result = ScheduleService._config({"day_of_week": 3})
        assert result == {"day_of_week": 3}

    def test_schedule_config_not_dict_ignored(self):
        result = ScheduleService._config({"schedule_config": "bad"})
        assert result == {}

    def test_prior_none(self):
        result = ScheduleService._config({"schedule_config": {"x": 1}}, prior=None)
        assert result == {"x": 1}


# ===================================================================
# _next_run
# ===================================================================

class TestNextRun:
    def test_once(self):
        job = _make_job(schedule_kind="once", delay_seconds=120)
        after = datetime(2026, 1, 1, 10, 0)
        result = ScheduleService._next_run(job, after=after)
        assert result == datetime(2026, 1, 1, 10, 2)

    def test_interval(self):
        job = _make_job(schedule_kind="interval", interval_seconds=300)
        after = datetime(2026, 1, 1, 10, 0)
        result = ScheduleService._next_run(job, after=after)
        assert result == datetime(2026, 1, 1, 10, 5)

    def test_daily(self):
        job = _make_job(
            schedule_kind="daily",
            timezone="UTC",
            schedule_config=json.dumps({"time_of_day": "08:00"}),
        )
        after = datetime(2026, 1, 1, 10, 0)
        result = ScheduleService._next_run(job, after=after)
        assert result == datetime(2026, 1, 2, 8, 0)

    def test_daily_before_target(self):
        job = _make_job(
            schedule_kind="daily",
            timezone="UTC",
            schedule_config=json.dumps({"time_of_day": "14:00"}),
        )
        after = datetime(2026, 1, 1, 10, 0)
        result = ScheduleService._next_run(job, after=after)
        assert result == datetime(2026, 1, 1, 14, 0)

    def test_weekly_same_day_later(self):
        job = _make_job(
            schedule_kind="weekly",
            timezone="UTC",
            schedule_config=json.dumps({"time_of_day": "09:00", "day_of_week": 3}),
        )
        # 2026-01-01 is Thursday (weekday=3)
        after = datetime(2026, 1, 1, 8, 0)
        result = ScheduleService._next_run(job, after=after)
        assert result == datetime(2026, 1, 1, 9, 0)

    def test_weekly_next_week(self):
        job = _make_job(
            schedule_kind="weekly",
            timezone="UTC",
            schedule_config=json.dumps({"time_of_day": "09:00", "day_of_week": 3}),
        )
        after = datetime(2026, 1, 1, 10, 0)  # Thursday 10:00
        result = ScheduleService._next_run(job, after=after)
        # Next Thursday is 2026-01-08
        assert result == datetime(2026, 1, 8, 9, 0)

    def test_weekly_different_day(self):
        job = _make_job(
            schedule_kind="weekly",
            timezone="UTC",
            schedule_config=json.dumps({"time_of_day": "09:00", "day_of_week": 0}),
        )
        after = datetime(2026, 1, 1, 10, 0)  # Thursday
        result = ScheduleService._next_run(job, after=after)
        assert result == datetime(2026, 1, 5, 9, 0)  # Monday

    def test_daily_no_config_key_raises(self):
        job = _make_job(
            schedule_kind="daily",
            timezone="UTC",
            schedule_config="{}",
        )
        after = datetime(2026, 1, 1, 10, 0)
        with pytest.raises(KeyError):
            ScheduleService._next_run(job, after=after)


# ===================================================================
# create_draft
# ===================================================================

class TestCreateDraft:
    @patch("services.schedule_service.ScheduleService._next_run")
    def test_basic(self, mock_next_run):
        mock_next_run.return_value = datetime(2026, 1, 2, 0, 0)
        db = MagicMock()
        svc = _svc(db)
        payload = {
            "agent_id": "agent_1",
            "schedule_kind": "once",
            "delay_seconds": 60,
            "input": "hello",
            "name": "my-schedule",
            "max_failures": 5,
        }
        job = svc.create_draft(1, payload)
        db.add.assert_called_once()
        db.flush.assert_called_once()
        db.commit.assert_called_once()
        db.refresh.assert_called_once()
        assert job.enabled is False

    def test_missing_agent_id_raises(self):
        svc = _svc()
        with pytest.raises(ValueError, match="agent_id required"):
            svc.create_draft(1, {"schedule_kind": "once", "delay_seconds": 10})

    @patch("services.schedule_service.ScheduleService._next_run")
    def test_no_commit(self, mock_next_run):
        mock_next_run.return_value = datetime(2026, 1, 2, 0, 0)
        db = MagicMock()
        svc = _svc(db)
        payload = {"agent_id": "a1", "schedule_kind": "once", "delay_seconds": 60}
        svc.create_draft(1, payload, commit=False)
        db.flush.assert_called_once()
        db.commit.assert_not_called()

    @patch("services.schedule_service.ScheduleService._next_run")
    def test_invalid_payload_raises(self, mock_next_run):
        svc = _svc()
        with pytest.raises(ValueError):
            svc.create_draft(1, {"agent_id": "a1", "schedule_kind": "bad_kind"})


# ===================================================================
# list / owned
# ===================================================================

class TestListOwned:
    def test_list(self):
        db = MagicMock()
        svc = _svc(db)
        mock_q = MagicMock()
        db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.order_by.return_value = mock_q
        mock_q.all.return_value = ["j1", "j2"]
        result = svc.list(1)
        assert result == ["j1", "j2"]

    def test_owned_found(self):
        db = MagicMock()
        svc = _svc(db)
        mock_q = MagicMock()
        db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.first.return_value = "the_job"
        result = svc.owned(1, "job_123")
        assert result == "the_job"

    def test_owned_not_found(self):
        db = MagicMock()
        svc = _svc(db)
        mock_q = MagicMock()
        db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.first.return_value = None
        result = svc.owned(1, "job_missing")
        assert result is None


# ===================================================================
# update_draft
# ===================================================================

class TestUpdateDraft:
    def test_enabled_job_raises(self):
        job = _make_job(enabled=True)
        svc = _svc()
        with pytest.raises(ValueError, match="pause schedule before editing"):
            svc.update_draft(job, {})

    @patch("services.schedule_service.ScheduleService._next_run")
    def test_update_name_and_max_failures(self, mock_next_run):
        mock_next_run.return_value = datetime(2026, 1, 2, 0, 0)
        db = MagicMock()
        svc = _svc(db)
        job = _make_job(enabled=False)
        result = svc.update_draft(job, {"name": "new-name", "max_failures": 10})
        assert job.name == "new-name"
        assert job.max_failures == 10
        db.commit.assert_called_once()

    @patch("services.schedule_service.ScheduleService._next_run")
    def test_update_input_metadata(self, mock_next_run):
        mock_next_run.return_value = datetime(2026, 1, 2, 0, 0)
        db = MagicMock()
        svc = _svc(db)
        job = _make_job(enabled=False, run_spec=json.dumps({"agent_id": "a1"}))
        svc.update_draft(job, {"input": "new input", "metadata": {"k": "v"}})
        spec = json.loads(job.run_spec)
        assert spec["input"] == "new input"
        assert spec["metadata"] == {"k": "v"}

    @patch("services.schedule_service.ScheduleService._next_run")
    def test_no_commit(self, mock_next_run):
        mock_next_run.return_value = datetime(2026, 1, 2, 0, 0)
        db = MagicMock()
        svc = _svc(db)
        job = _make_job(enabled=False)
        svc.update_draft(job, {"name": "x"}, commit=False)
        db.flush.assert_called_once()
        db.commit.assert_not_called()


# ===================================================================
# preview
# ===================================================================

class TestPreview:
    def test_once_with_next_run(self):
        job = _make_job(schedule_kind="once", next_run_at=datetime(2026, 1, 1, 12, 0))
        result = ScheduleService(_MagicDB()).preview(job, count=5)
        assert result == ["2026-01-01T12:00:00"]

    def test_once_no_next_run(self):
        job = _make_job(schedule_kind="once", next_run_at=None)
        result = ScheduleService(_MagicDB()).preview(job)
        assert result == []

    def test_interval(self):
        job = _make_job(
            schedule_kind="interval",
            interval_seconds=60,
            next_run_at=datetime(2026, 1, 1, 12, 0),
            timezone="UTC",
            schedule_config="{}",
        )
        result = ScheduleService(_MagicDB()).preview(job, count=3)
        assert len(result) == 3

    def test_count_clamped(self):
        job = _make_job(
            schedule_kind="interval",
            interval_seconds=60,
            next_run_at=datetime(2026, 1, 1, 12, 0),
            timezone="UTC",
            schedule_config="{}",
        )
        result = ScheduleService(_MagicDB()).preview(job, count=100)
        assert len(result) == 10

    def test_no_next_run_fallback(self):
        job = _make_job(
            schedule_kind="daily",
            timezone="UTC",
            schedule_config=json.dumps({"time_of_day": "09:00"}),
            next_run_at=None,
        )
        with patch.object(ScheduleService, "_utcnow", return_value=datetime(2026, 1, 1, 0, 0)):
            result = ScheduleService(_MagicDB()).preview(job, count=1)
        assert len(result) >= 1

    def test_preview_cursor_none_breaks(self):
        job = _make_job(
            schedule_kind="interval",
            interval_seconds=60,
            next_run_at=datetime(2026, 1, 1, 12, 0),
            timezone="UTC",
            schedule_config="{}",
        )
        with patch.object(ScheduleService, "_next_run", side_effect=[datetime(2026, 1, 1, 12, 1), None]):
            result = ScheduleService(_MagicDB()).preview(job, count=5)
        assert len(result) == 2


class _MagicDB:
    def __init__(self):
        self._q = MagicMock()
    def query(self, *a, **kw):
        return self._q


# ===================================================================
# enable / enable_desired / arm_enabled
# ===================================================================

class TestEnable:
    def test_enable_already_enabled(self):
        job = _make_job(enabled=True)
        runtime = MagicMock()
        result = ScheduleService(MagicMock()).enable(job, runtime, lambda jid: lambda _: None)
        assert result is job

    @patch("services.schedule_service.ScheduleService._next_run")
    @patch("services.schedule_service.ScheduleService._arm")
    def test_enable_sets_next_run_when_none(self, mock_arm, mock_next_run):
        mock_next_run.return_value = datetime(2026, 1, 2, 0, 0)
        db = MagicMock()
        job = _make_job(enabled=False, next_run_at=None)
        runtime = MagicMock()
        svc = _svc(db)
        result = svc.enable(job, runtime, lambda jid: lambda _: None)
        assert result.enabled is True
        assert result.pending_trigger is False
        mock_arm.assert_called_once()
        db.commit.assert_called_once()

    @patch("services.schedule_service.ScheduleService._next_run")
    @patch("services.schedule_service.ScheduleService._arm")
    def test_enable_refreshes_next_run_when_overdue(self, mock_arm, mock_next_run):
        mock_next_run.return_value = datetime(2026, 1, 2, 0, 0)
        db = MagicMock()
        job = _make_job(enabled=False, next_run_at=datetime(2025, 1, 1))
        runtime = MagicMock()
        svc = _svc(db)
        svc.enable(job, runtime, lambda jid: lambda _: None)
        mock_next_run.assert_called()


class TestEnableDesired:
    def test_already_enabled(self):
        job = _make_job(enabled=True)
        result = ScheduleService(MagicMock()).enable_desired(job)
        assert result is job

    @patch("services.schedule_service.ScheduleService._next_run")
    def test_sets_enabled(self, mock_next_run):
        mock_next_run.return_value = datetime(2026, 1, 2, 0, 0)
        db = MagicMock()
        job = _make_job(enabled=False, next_run_at=None)
        result = ScheduleService(_svc(db).db if False else db).enable_desired(job)
        # access svc through direct construction
        svc = ScheduleService(db)
        job2 = _make_job(enabled=False, next_run_at=None)
        svc.enable_desired(job2)
        assert job2.enabled is True
        assert job2.pending_trigger is False
        assert job2.runtime_job_id is None

    @patch("services.schedule_service.ScheduleService._next_run")
    def test_no_commit(self, mock_next_run):
        mock_next_run.return_value = datetime(2026, 1, 2, 0, 0)
        db = MagicMock()
        job = _make_job(enabled=False, next_run_at=None)
        svc = ScheduleService(db)
        svc.enable_desired(job, commit=False)
        db.flush.assert_called_once()
        db.commit.assert_not_called()


class TestArmEnabled:
    def test_not_enabled_noop(self):
        job = _make_job(enabled=False)
        runtime = MagicMock()
        svc = ScheduleService(MagicMock())
        result = svc.arm_enabled(job, runtime, lambda jid: lambda _: None)
        assert result is job

    def test_already_has_runtime_id_noop(self):
        job = _make_job(enabled=True, runtime_job_id="existing_id")
        runtime = MagicMock()
        svc = ScheduleService(MagicMock())
        result = svc.arm_enabled(job, runtime, lambda jid: lambda _: None)
        assert result is job

    @patch("services.schedule_service.ScheduleService._arm")
    def test_arms_and_commits(self, mock_arm):
        job = _make_job(enabled=True, runtime_job_id=None)
        runtime = MagicMock()
        db = MagicMock()
        svc = ScheduleService(db)
        result = svc.arm_enabled(job, runtime, lambda jid: lambda _: None)
        db.commit.assert_called_once()
        assert result is job

    @patch("services.schedule_service.ScheduleService._arm")
    def test_rollback_on_arm_failure(self, mock_arm):
        mock_arm.side_effect = RuntimeError("arm failed")
        job = _make_job(enabled=True, runtime_job_id=None)
        runtime = MagicMock()
        db = MagicMock()
        svc = ScheduleService(db)
        with pytest.raises(RuntimeError):
            svc.arm_enabled(job, runtime, lambda jid: lambda _: None)
        db.rollback.assert_called_once()

    @patch("services.schedule_service.ScheduleService._arm")
    def test_rollback_cancel_schedule_also_fails(self, mock_arm):
        def arm_sets_runtime(job, runtime, cb):
            job.runtime_job_id = "rt_new"
        mock_arm.side_effect = arm_sets_runtime
        job = _make_job(enabled=True, runtime_job_id=None, user_id=1)
        runtime = MagicMock()
        runtime.cancel_schedule.side_effect = RuntimeError("cancel failed too")
        db = MagicMock()
        db.commit.side_effect = RuntimeError("commit failed")
        svc = ScheduleService(db)
        with pytest.raises(RuntimeError):
            svc.arm_enabled(job, runtime, lambda jid: lambda _: None)
        db.rollback.assert_called_once()
        runtime.cancel_schedule.assert_called_once()


# ===================================================================
# pause / pause_desired
# ===================================================================

class TestPause:
    def test_cancels_runtime_and_disables(self):
        job = _make_job(enabled=True, runtime_job_id="rt_123", user_id=1)
        runtime = MagicMock()
        db = MagicMock()
        svc = ScheduleService(db)
        result = svc.pause(job, runtime)
        runtime.cancel_schedule.assert_called_once_with("rt_123", user_id=1)
        assert result.enabled is False
        assert result.runtime_job_id is None
        assert result.pending_trigger is False
        db.commit.assert_called_once()

    def test_no_runtime_job(self):
        job = _make_job(enabled=True, runtime_job_id=None)
        runtime = MagicMock()
        db = MagicMock()
        svc = ScheduleService(db)
        svc.pause(job, runtime)
        runtime.cancel_schedule.assert_not_called()


class TestPauseDesired:
    def test_returns_runtime_job_id(self):
        job = _make_job(enabled=True, runtime_job_id="rt_456")
        db = MagicMock()
        svc = ScheduleService(db)
        result_job, rt_id = svc.pause_desired(job)
        assert rt_id == "rt_456"
        assert result_job.enabled is False
        assert result_job.runtime_job_id is None

    def test_no_commit(self):
        job = _make_job(enabled=True, runtime_job_id="rt_789")
        db = MagicMock()
        svc = ScheduleService(db)
        svc.pause_desired(job, commit=False)
        db.flush.assert_called_once()
        db.commit.assert_not_called()


# ===================================================================
# delete / delete_desired
# ===================================================================

class TestDelete:
    def test_deletes_with_runtime(self):
        job = _make_job(runtime_job_id="rt_del", user_id=2)
        runtime = MagicMock()
        db = MagicMock()
        svc = ScheduleService(db)
        svc.delete(job, runtime)
        runtime.cancel_schedule.assert_called_once_with("rt_del", user_id=2)
        db.delete.assert_called_once_with(job)
        db.commit.assert_called_once()

    def test_deletes_without_runtime(self):
        job = _make_job(runtime_job_id=None)
        runtime = MagicMock()
        db = MagicMock()
        svc = ScheduleService(db)
        svc.delete(job, runtime)
        runtime.cancel_schedule.assert_not_called()
        db.delete.assert_called_once()


class TestDeleteDesired:
    def test_returns_runtime_id(self):
        job = _make_job(runtime_job_id="rt_x")
        db = MagicMock()
        svc = ScheduleService(db)
        rt_id = svc.delete_desired(job)
        assert rt_id == "rt_x"
        db.delete.assert_called_once_with(job)

    def test_no_commit(self):
        job = _make_job(runtime_job_id=None)
        db = MagicMock()
        svc = ScheduleService(db)
        rt_id = svc.delete_desired(job, commit=False)
        assert rt_id is None
        db.flush.assert_called_once()
        db.commit.assert_not_called()


# ===================================================================
# claim_occurrence
# ===================================================================

class TestClaimOccurrence:
    def test_disabled_job(self):
        job = _make_job(enabled=False)
        db = MagicMock()
        svc = ScheduleService(db)
        decision, claim = svc.claim_occurrence(job)
        assert decision == "disabled"
        assert claim is None

    def test_require_enabled_false_allows_disabled(self):
        job = _make_job(enabled=False)
        db = MagicMock()
        svc = ScheduleService(db)
        mock_q = MagicMock()
        db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.first.return_value = None
        mock_q.join.return_value.filter.return_value.count.return_value = 0
        decision, claim = svc.claim_occurrence(job, require_enabled=False)
        assert decision == "run"
        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_no_existing_duplicate(self):
        job = _make_job(enabled=True)
        db = MagicMock()
        svc = ScheduleService(db)
        mock_q = MagicMock()
        db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.first.return_value = None
        mock_q.join.return_value.filter.return_value.count.return_value = 0
        decision, claim = svc.claim_occurrence(job)
        assert decision == "run"
        assert claim is not None

    def test_existing_duplicate(self):
        job = _make_job(enabled=True)
        existing = _make_claim(outcome="triggered")
        db = MagicMock()
        svc = ScheduleService(db)
        mock_q = MagicMock()
        db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.first.return_value = existing
        decision, claim = svc.claim_occurrence(job)
        assert decision == "duplicate"
        assert claim is existing

    def test_existing_queued_returns_pending(self):
        job = _make_job(enabled=True)
        existing = _make_claim(outcome="queued")
        db = MagicMock()
        svc = ScheduleService(db)
        mock_q = MagicMock()
        db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.first.return_value = existing
        decision, claim = svc.claim_occurrence(job)
        assert decision == "pending"
        assert claim is existing

    def test_skip_concurrency(self):
        job = _make_job(enabled=True, concurrency_policy="skip")
        db = MagicMock()
        svc = ScheduleService(db)
        mock_q = MagicMock()
        db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.first.return_value = None  # no existing occurrence
        mock_q.join.return_value.filter.return_value.count.return_value = 1  # active run exists
        decision, claim = svc.claim_occurrence(job)
        assert decision == "skipped"
        assert claim is not None
        assert claim.outcome == "skipped_concurrency"

    def test_queue_one_concurrency_new_queue(self):
        job = _make_job(enabled=True, concurrency_policy="queue_one")
        db = MagicMock()
        svc = ScheduleService(db)
        mock_q = MagicMock()
        db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.first.side_effect = [None, None]  # existing check → None, queue check → None
        mock_q.join.return_value.filter.return_value.count.return_value = 1
        decision, claim = svc.claim_occurrence(job)
        assert decision == "queued"
        assert claim.outcome == "queued"

    def test_queue_one_concurrency_existing_queue(self):
        job = _make_job(enabled=True, concurrency_policy="queue_one")
        existing_queue = _make_claim(outcome="queued", occurrence_key="queue:job_abc123")
        db = MagicMock()
        svc = ScheduleService(db)
        mock_q = MagicMock()
        db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.first.side_effect = [None, existing_queue]
        mock_q.join.return_value.filter.return_value.count.return_value = 1
        decision, claim = svc.claim_occurrence(job)
        assert decision == "pending"

    def test_manual_trigger_kind(self):
        job = _make_job(enabled=True)
        db = MagicMock()
        svc = ScheduleService(db)
        mock_q = MagicMock()
        db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.first.return_value = None
        mock_q.join.return_value.filter.return_value.count.return_value = 0
        decision, claim = svc.claim_occurrence(job, trigger_kind="manual", operation_id="op_1")
        assert decision == "run"
        assert claim.occurrence_key.startswith("manual:")

    def test_queue_recheck_reclaims_queued(self):
        job = _make_job(enabled=True)
        existing = _make_claim(outcome="queued", occurrence_key="queue:job_abc123")
        db = MagicMock()
        svc = ScheduleService(db)
        mock_q = MagicMock()
        db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.first.return_value = existing  # existing occurrence found (queued)
        mock_q.join.return_value.filter.return_value.count.return_value = 0  # no active runs
        decision, claim = svc.claim_occurrence(job, trigger_kind="queue_recheck")
        assert decision == "run"
        assert claim.outcome == "claimed"
        assert claim.claim_token is not None

    def test_queue_recheck_existing_not_queued(self):
        job = _make_job(enabled=True)
        existing = _make_claim(outcome="triggered", occurrence_key="queue:job_abc123")
        db = MagicMock()
        svc = ScheduleService(db)
        mock_q = MagicMock()
        db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.first.return_value = existing
        decision, claim = svc.claim_occurrence(job, trigger_kind="queue_recheck")
        assert decision == "duplicate"

    def test_integrity_error_fallback(self):
        job = _make_job(enabled=True)
        db = MagicMock()
        svc = ScheduleService(db)
        mock_q1 = MagicMock()
        mock_q2 = MagicMock()
        mock_q3 = MagicMock()
        db.query.side_effect = [mock_q1, mock_q2, mock_q3]
        mock_q1.filter.return_value = mock_q1
        mock_q1.first.return_value = None
        mock_q2.join.return_value.filter.return_value.count.return_value = 0
        db.commit.side_effect = IntegrityError("ix", {}, Exception("dup"))
        fallback_existing = _make_claim(outcome="queued")
        mock_q3.filter.return_value = mock_q3
        mock_q3.first.return_value = fallback_existing
        decision, claim = svc.claim_occurrence(job)
        assert decision == "pending"
        assert claim is fallback_existing

    def test_integrity_error_no_queued_fallback(self):
        job = _make_job(enabled=True)
        db = MagicMock()
        svc = ScheduleService(db)
        mock_q1 = MagicMock()
        mock_q2 = MagicMock()
        mock_q3 = MagicMock()
        db.query.side_effect = [mock_q1, mock_q2, mock_q3]
        mock_q1.filter.return_value = mock_q1
        mock_q1.first.return_value = None
        mock_q2.join.return_value.filter.return_value.count.return_value = 0
        db.commit.side_effect = IntegrityError("ix", {}, Exception("dup"))
        mock_q3.filter.return_value = mock_q3
        mock_q3.first.return_value = None
        decision, claim = svc.claim_occurrence(job)
        assert decision == "duplicate"
        assert claim is None


# ===================================================================
# bind_claim_to_run / fail_claim
# ===================================================================

class TestBindClaimToRun:
    def test_binds(self):
        claim = _make_claim()
        db = MagicMock()
        svc = ScheduleService(db)
        result = svc.bind_claim_to_run(claim, "run_999")
        assert result.agent_run_id == "run_999"
        assert result.outcome == "triggered"
        assert result.claim_expires_at is None
        db.commit.assert_called_once()


class TestFailClaim:
    def test_fails_with_error_code(self):
        claim = _make_claim()
        err = Exception("boom")
        err.code = "MY_ERR"
        db = MagicMock()
        svc = ScheduleService(db)
        result = svc.fail_claim(claim, err)
        assert result.outcome == "failed_to_create"
        assert result.error_code == "MY_ERR"
        assert result.finished_at is not None
        db.commit.assert_called_once()

    def test_fails_without_error_code(self):
        claim = _make_claim()
        err = Exception("oops")
        db = MagicMock()
        svc = ScheduleService(db)
        result = svc.fail_claim(claim, err)
        assert result.error_code == "SCHEDULE_RUN_CREATE_FAILED"


# ===================================================================
# active_run_count
# ===================================================================

class TestActiveRunCount:
    def test_returns_count(self):
        db = MagicMock()
        svc = ScheduleService(db)
        mock_q = MagicMock()
        db.query.return_value = mock_q
        mock_q.join.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.count.return_value = 3
        result = svc.active_run_count(_make_job())
        assert result == 3


# ===================================================================
# claim_trigger
# ===================================================================

class TestClaimTrigger:
    def test_sets_pending_trigger_on_queued(self):
        job = _make_job(enabled=True, concurrency_policy="queue_one")
        db = MagicMock()
        svc = ScheduleService(db)
        mock_q = MagicMock()
        db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.first.side_effect = [None, None]  # existing → None, queue → None
        mock_q.join.return_value.filter.return_value.count.return_value = 1
        decision = svc.claim_trigger(job)
        assert decision == "queued"
        assert job.pending_trigger is True
        assert db.commit.call_count == 2  # once in claim_occurrence, once in claim_trigger

    def test_clears_pending_trigger_on_run(self):
        job = _make_job(enabled=True, pending_trigger=True)
        db = MagicMock()
        svc = ScheduleService(db)
        mock_q = MagicMock()
        db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.first.return_value = None
        mock_q.join.return_value.filter.return_value.count.return_value = 0
        decision = svc.claim_trigger(job)
        assert decision == "run"
        assert job.pending_trigger is False


# ===================================================================
# defer_pending
# ===================================================================

class TestDeferPending:
    def test_schedules_recheck(self):
        job = _make_job(run_spec=json.dumps({"agent_id": "a1"}), user_id=1)
        runtime = MagicMock()
        db = MagicMock()
        svc = ScheduleService(db)
        svc.defer_pending(job, runtime, lambda jid: lambda _: None, seconds=10.0)
        runtime.schedule_once.assert_called_once()
        call_args = runtime.schedule_once.call_args
        assert call_args[0][0] == 10.0
        assert call_args[0][1]["_schedule_queue_recheck"] is True
        assert call_args[1]["user_id"] == 1


# ===================================================================
# advance_after_callback
# ===================================================================

class TestAdvanceAfterCallback:
    def test_once_disables(self):
        job = _make_job(schedule_kind="once", runtime_job_id="rt_1")
        runtime = MagicMock()
        db = MagicMock()
        svc = ScheduleService(db)
        with patch.object(ScheduleService, "_utcnow", return_value=datetime(2026, 6, 1)):
            svc.advance_after_callback(job, runtime, lambda jid: lambda _: None)
        assert job.enabled is False
        assert job.runtime_job_id is None
        assert job.next_run_at is None
        assert job.last_run_at == datetime(2026, 6, 1)
        db.commit.assert_called_once()

    @patch("services.schedule_service.ScheduleService._next_run")
    @patch("services.schedule_service.ScheduleService._arm")
    def test_recurring_advances_next_run(self, mock_arm, mock_next_run):
        mock_next_run.return_value = datetime(2026, 6, 2)
        job = _make_job(schedule_kind="interval", runtime_job_id="rt_2")
        runtime = MagicMock()
        db = MagicMock()
        svc = ScheduleService(db)
        with patch.object(ScheduleService, "_utcnow", return_value=datetime(2026, 6, 1)):
            svc.advance_after_callback(job, runtime, lambda jid: lambda _: None)
        assert job.next_run_at == datetime(2026, 6, 2)
        mock_arm.assert_called_once()


# ===================================================================
# record_execution
# ===================================================================

class TestRecordExecution:
    def test_success_resets_failure_count(self):
        job = _make_job(failure_count=5)
        db = MagicMock()
        svc = ScheduleService(db)
        result = svc.record_execution(job, "run_1", "triggered")
        assert job.failure_count == 0
        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_error_increments_failure(self):
        job = _make_job(failure_count=1, max_failures=3, enabled=True)
        db = MagicMock()
        svc = ScheduleService(db)
        err = Exception("fail")
        svc.record_execution(job, None, "failed", error=err)
        assert job.failure_count == 2
        assert job.enabled is True

    def test_error_disables_on_max_failures(self):
        job = _make_job(failure_count=2, max_failures=3, runtime_job_id="rt_x")
        db = MagicMock()
        svc = ScheduleService(db)
        err = Exception("fail")
        svc.record_execution(job, None, "failed", error=err)
        assert job.failure_count == 3
        assert job.enabled is False
        assert job.runtime_job_id is None

    def test_with_run_id(self):
        job = _make_job()
        db = MagicMock()
        svc = ScheduleService(db)
        svc.record_execution(job, "run_abc", "triggered")
        db.add.assert_called_once()


# ===================================================================
# restore_enabled
# ===================================================================

class TestRestoreEnabled:
    def test_overdue_once_skipped_and_disabled(self):
        job = _make_job(
            enabled=True,
            schedule_kind="once",
            next_run_at=datetime(2025, 6, 1),
            runtime_job_id="old_rt",
        )
        db = MagicMock()
        svc = ScheduleService(db)
        mock_q = MagicMock()
        db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.all.return_value = [job]
        runtime = MagicMock()
        with patch.object(ScheduleService, "_utcnow", return_value=datetime(2026, 1, 1)):
            count = svc.restore_enabled(runtime, lambda jid: lambda _: None)
        assert count == 0
        assert job.enabled is False
        assert job.next_run_at is None
        assert job.runtime_job_id is None
        db.add.assert_called_once()  # skipped_misfire execution
        db.commit.assert_called_once()

    def test_overdue_recurring_advances(self):
        job = _make_job(
            enabled=True,
            schedule_kind="interval",
            interval_seconds=300,
            next_run_at=datetime(2025, 6, 1),
            timezone="UTC",
            schedule_config="{}",
            runtime_job_id=None,
        )
        db = MagicMock()
        svc = ScheduleService(db)
        mock_q = MagicMock()
        db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.all.return_value = [job]
        runtime = MagicMock()
        with patch.object(ScheduleService, "_utcnow", return_value=datetime(2026, 1, 1)):
            count = svc.restore_enabled(runtime, lambda jid: lambda _: None)
        assert count == 1
        assert job.next_run_at is not None
        assert job.next_run_at > datetime(2026, 1, 1)

    def test_future_job_just_arms(self):
        job = _make_job(
            enabled=True,
            schedule_kind="once",
            delay_seconds=300,
            next_run_at=datetime(2026, 12, 1),
            runtime_job_id=None,
        )
        db = MagicMock()
        svc = ScheduleService(db)
        mock_q = MagicMock()
        db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.all.return_value = [job]
        runtime = MagicMock()
        with patch.object(ScheduleService, "_utcnow", return_value=datetime(2026, 1, 1)):
            count = svc.restore_enabled(runtime, lambda jid: lambda _: None)
        assert count == 1
        runtime.schedule_once.assert_called_once()

    def test_no_jobs(self):
        db = MagicMock()
        svc = ScheduleService(db)
        mock_q = MagicMock()
        db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.all.return_value = []
        runtime = MagicMock()
        with patch.object(ScheduleService, "_utcnow", return_value=datetime(2026, 1, 1)):
            count = svc.restore_enabled(runtime, lambda jid: lambda _: None)
        assert count == 0


# ===================================================================
# executions
# ===================================================================

class TestExecutions:
    def test_returns_executions(self):
        db = MagicMock()
        svc = ScheduleService(db)
        mock_q = MagicMock()
        db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.order_by.return_value = mock_q
        mock_q.limit.return_value = mock_q
        mock_q.all.return_value = ["e1", "e2"]
        result = svc.executions(_make_job(), limit=50)
        assert result == ["e1", "e2"]
        mock_q.limit.assert_called_with(50)

    def test_default_limit(self):
        db = MagicMock()
        svc = ScheduleService(db)
        mock_q = MagicMock()
        db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.order_by.return_value = mock_q
        mock_q.limit.return_value = mock_q
        mock_q.all.return_value = []
        svc.executions(_make_job())
        mock_q.limit.assert_called_with(100)


# ===================================================================
# _occurrence_key
# ===================================================================

class TestOccurrenceKey:
    def test_manual(self):
        job = _make_job()
        svc = _svc()
        key = svc._occurrence_key(job, "manual", "op_1")
        assert key == "manual:job_abc123:op_1"

    def test_manual_no_op(self):
        job = _make_job()
        svc = _svc()
        key = svc._occurrence_key(job, "manual")
        assert key.startswith("manual:job_abc123:")

    def test_queue_recheck(self):
        job = _make_job()
        svc = _svc()
        key = svc._occurrence_key(job, "queue_recheck")
        assert key == "queue:job_abc123"

    def test_schedule(self):
        job = _make_job(next_run_at=datetime(2026, 3, 15, 8, 30))
        svc = _svc()
        key = svc._occurrence_key(job, "schedule")
        assert key == "schedule:job_abc123:2026-03-15T08:30:00"


# ===================================================================
# _arm (indirect coverage via enable/advance)
# ===================================================================

class TestArm:
    def test_arm_disabled_noop(self):
        job = _make_job(enabled=False, runtime_job_id="old")
        runtime = MagicMock()
        db = MagicMock()
        svc = ScheduleService(db)
        svc._arm(job, runtime, lambda jid: lambda _: None)
        assert job.runtime_job_id is None

    def test_arm_no_next_run_noop(self):
        job = _make_job(enabled=True, next_run_at=None, runtime_job_id="old")
        runtime = MagicMock()
        db = MagicMock()
        svc = ScheduleService(db)
        svc._arm(job, runtime, lambda jid: lambda _: None)
        assert job.runtime_job_id is None

    def test_arm_schedules(self):
        job = _make_job(enabled=True, next_run_at=datetime(2026, 1, 2), user_id=5)
        runtime = MagicMock()
        db = MagicMock()
        svc = ScheduleService(db)
        with patch.object(ScheduleService, "_utcnow", return_value=datetime(2026, 1, 1)):
            svc._arm(job, runtime, lambda jid: lambda _: None)
        runtime.schedule_once.assert_called_once()
        assert job.runtime_job_id is not None
