"""Timeouts enforce process termination: the child is stopped and gone before a job is recorded."""

import os
import time

import pytest
from sqlalchemy.orm import Session

from app.models import AnalysisJob, JobStatus, Sample
from app.services import job_service, process_runner


@pytest.fixture()
def storage_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job_service.storage, "load", lambda sha: b"MZ")


def _job(db: Session, sha: str, executor: str) -> AnalysisJob:
    sample = Sample(
        sha256=sha, filename="s.bin", size_bytes=2, detected_type="pe", stored_path="unused"
    )
    db.add(sample)
    db.flush()
    job = AnalysisJob(sample_id=sample.id, executor=executor, conditions={})
    db.add(job)
    db.flush()
    return job


def test_timeout_stops_the_child_and_records_timed_out(
    db_session: Session, storage_ok: None
) -> None:
    job = _job(db_session, "d" * 64, "hanging")  # sleeps far past the 1-second limit

    started = time.monotonic()
    job_service.run_job(db_session, job, timeout_seconds=1)
    elapsed = time.monotonic() - started

    assert elapsed < 10, "the hung child must be terminated, not waited for"
    assert job.status == JobStatus.timed_out
    assert job.error == "execution exceeded timeout"
    assert job.finished_at is not None


def test_timed_out_child_process_group_is_gone(storage_ok: None) -> None:
    outcome = process_runner.run_in_child(
        executor_name="hanging",
        sample_sha256="e" * 64,
        conditions={},
        timeout_seconds=1,
    )
    assert outcome.kind == "timed_out"
    assert outcome.pid is not None
    if os.name == "posix":
        with pytest.raises(ProcessLookupError):
            os.killpg(outcome.pid, 0)  # no member of the child's group remains


def test_child_that_ignores_sigterm_is_killed(storage_ok: None) -> None:
    started = time.monotonic()
    outcome = process_runner.run_in_child(
        executor_name="stubborn",
        sample_sha256="f" * 64,
        conditions={},
        timeout_seconds=1,
    )
    elapsed = time.monotonic() - started

    assert outcome.kind == "timed_out"  # recorded only after SIGKILL confirmed the group is gone
    assert elapsed < 1 + process_runner.GRACE_SECONDS + 5
