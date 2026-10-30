"""Executor child processes: success, crashes, cancellation, and heartbeat-driven termination."""

import os
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import AnalysisJob, JobStatus, Sample
from app.services import emergency_service, job_service, process_runner
from app.services.worker_service import LeaseHeartbeat, claim_next


@pytest.fixture()
def storage_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job_service.storage, "load", lambda sha: b"MZ")


def _group_gone(pid: int | None) -> bool:
    if pid is None or os.name != "posix":
        return True
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return True
    return False


def test_simulated_run_completes_in_a_child_process(storage_ok: None) -> None:
    outcome = process_runner.run_in_child(
        executor_name="simulated",
        sample_sha256="a" * 64,
        conditions={"internet": True},
        timeout_seconds=30,
    )
    assert outcome.kind == "completed"
    assert outcome.observations  # the simulated behaviour came back through the child
    assert outcome.pid is not None and outcome.pid != os.getpid()
    assert _group_gone(outcome.pid)


def test_child_crash_is_recorded_as_failed_with_no_details(storage_ok: None) -> None:
    outcome = process_runner.run_in_child(
        executor_name="crashing", sample_sha256="b" * 64, conditions={}, timeout_seconds=30
    )
    assert outcome.kind == "failed"
    assert outcome.error == "executor process exited unexpectedly"
    assert outcome.observations is None


def test_unknown_executor_in_child_is_an_invalid_request(storage_ok: None) -> None:
    outcome = process_runner.run_in_child(
        executor_name="no-such-executor", sample_sha256="c" * 64, conditions={}, timeout_seconds=30
    )
    assert outcome.kind == "failed"
    assert outcome.error == "executor process exited unexpectedly"


def test_cancel_signal_stops_a_running_child_and_it_is_gone(storage_ok: None) -> None:
    cancel = process_runner.CancelSignal()
    threading.Timer(0.5, cancel.set, args=("cancelled while running",)).start()

    started = time.monotonic()
    outcome = process_runner.run_in_child(
        executor_name="hanging",
        sample_sha256="d" * 64,
        conditions={},
        timeout_seconds=30,
        cancel=cancel,
    )
    assert time.monotonic() - started < 10
    assert outcome.kind == "cancelled"
    assert outcome.error == "cancelled while running"
    assert _group_gone(outcome.pid)


@pytest.fixture()
def file_db(tmp_path: Path):  # type: ignore[no-untyped-def]
    engine = create_engine(f"sqlite:///{tmp_path / 'proc.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    yield factory
    engine.dispose()


def _claimed_job(factory, executor: str, owner: str, lease: timedelta) -> int:  # type: ignore[no-untyped-def]
    with factory() as db:
        sample = Sample(
            sha256="9" * 64, filename="p.bin", size_bytes=2, detected_type="pe", stored_path="u"
        )
        db.add(sample)
        db.commit()
        job_id = job_service.create_job(
            db, sample_id=sample.id, executor_name=executor, conditions={}, submitted_by=None
        ).id
        assert claim_next(db, owner=owner, lease=lease) == job_id
    return job_id


def test_heartbeat_signals_cancel_when_a_stop_is_requested(file_db) -> None:  # type: ignore[no-untyped-def]
    job_id = _claimed_job(file_db, "simulated", "w1", timedelta(seconds=30))
    heartbeat = LeaseHeartbeat(file_db, job_id, owner="w1")
    with file_db() as db:
        job = db.get(AnalysisJob, job_id)
        job.cancel_requested = True
        db.commit()
    assert heartbeat._tick() is False
    assert heartbeat.cancel.reason == "cancelled while running"


def test_heartbeat_signals_cancel_when_the_emergency_stop_is_active(file_db) -> None:  # type: ignore[no-untyped-def]
    job_id = _claimed_job(file_db, "simulated", "w1", timedelta(seconds=30))
    heartbeat = LeaseHeartbeat(file_db, job_id, owner="w1")
    with file_db() as db:
        emergency_service.set_active(db, active=True, actor_id=None)
        db.commit()
    assert heartbeat._tick() is False
    assert heartbeat.cancel.reason == "emergency stop: execution terminated"


def test_heartbeat_signals_cancel_when_the_lease_is_lost(file_db) -> None:  # type: ignore[no-untyped-def]
    job_id = _claimed_job(file_db, "simulated", "w1", timedelta(seconds=-1))  # already expired
    heartbeat = LeaseHeartbeat(file_db, job_id, owner="w1")
    assert heartbeat._tick() is False
    assert heartbeat.cancel.reason == "worker lease was lost"


def test_cancelled_running_job_records_cancelled_only_after_termination(
    file_db,
    storage_ok: None,  # type: ignore[no-untyped-def]
) -> None:
    job_id = _claimed_job(file_db, "hanging", "w1", timedelta(seconds=30))
    cancel = process_runner.CancelSignal()
    threading.Timer(0.5, cancel.set, args=("cancelled while running",)).start()
    with file_db() as db:
        job = db.get(AnalysisJob, job_id)
        job_service.run_job(db, job, owner="w1", cancel=cancel)
    with file_db() as db:
        job = db.get(AnalysisJob, job_id)
        assert job.status == JobStatus.cancelled
        assert job.error == "cancelled while running"
        assert job.result is None


def test_late_worker_cannot_overwrite_a_terminal_state(file_db, storage_ok: None) -> None:  # type: ignore[no-untyped-def]
    # A timed-out job, then a late completion from the same owner: the terminal state must hold.
    timed_out_id = _claimed_job(file_db, "simulated", "w1", timedelta(seconds=30))
    with file_db() as db:
        job_service._settle(
            db, db.get(AnalysisJob, timed_out_id), "w1", JobStatus.timed_out, error="x"
        )
    with file_db() as db:
        job_service._settle(
            db, db.get(AnalysisJob, timed_out_id), "w1", JobStatus.completed, error=None
        )
    with file_db() as db:
        job = db.get(AnalysisJob, timed_out_id)
        assert (job.status, job.error) == (JobStatus.timed_out, "x")


def test_expired_lease_cannot_record_cancelled_or_completed(file_db, storage_ok: None) -> None:  # type: ignore[no-untyped-def]
    job_id = _claimed_job(file_db, "simulated", "w1", timedelta(seconds=-1))  # already expired
    with file_db() as db:
        job_service._settle(db, db.get(AnalysisJob, job_id), "w1", JobStatus.cancelled, error="x")
    with file_db() as db:
        job = db.get(AnalysisJob, job_id)
        assert job.status == JobStatus.running  # recovery, not this worker, decides the outcome
        assert job.error is None
