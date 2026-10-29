import threading
import time

import pytest
from sqlalchemy.orm import Session

from app.executors import registry
from app.executors.base import ExecutionRequest, ExecutionResult
from app.models import AnalysisJob, JobStatus, Sample
from app.services import job_service


class GatedExecutor:
    """A harmless simulated executor that blocks until the test releases it."""

    name = "gated"

    def __init__(self) -> None:
        self.release = threading.Event()

    def run(self, request: ExecutionRequest) -> ExecutionResult:
        self.release.wait(10)
        return ExecutionResult(status="completed", duration_ms=0, observations={})


@pytest.fixture()
def gated(monkeypatch: pytest.MonkeyPatch) -> GatedExecutor:
    executor = GatedExecutor()
    monkeypatch.setitem(registry._EXECUTORS, executor.name, executor)
    monkeypatch.setattr(job_service.storage, "load", lambda sha: b"MZ")
    yield executor
    executor.release.set()  # let any abandoned worker thread finish during teardown


def _job(db: Session, sha: str) -> AnalysisJob:
    sample = Sample(
        sha256=sha,
        filename="s.bin",
        size_bytes=2,
        detected_type="pe",
        stored_path="unused",
    )
    db.add(sample)
    db.flush()
    job = AnalysisJob(sample_id=sample.id, executor="gated", conditions={})
    db.add(job)
    db.flush()
    return job


def test_timeout_returns_without_waiting_for_the_executor(
    db_session: Session, gated: GatedExecutor
) -> None:
    job = _job(db_session, "d" * 64)

    started = time.monotonic()
    job_service.run_job(db_session, job, timeout_seconds=1)
    elapsed = time.monotonic() - started

    # The executor is still blocked here. Waiting for it would take up to 10 seconds.
    assert elapsed < 5
    assert job.status == JobStatus.timed_out
    assert job.error == "execution exceeded timeout"
    assert job.finished_at is not None


def test_late_result_cannot_overwrite_timed_out_status(
    db_session: Session, gated: GatedExecutor
) -> None:
    job = _job(db_session, "e" * 64)
    job_service.run_job(db_session, job, timeout_seconds=1)

    # Let the abandoned executor finish and return a "completed" result.
    gated.release.set()
    time.sleep(0.3)

    assert job.status == JobStatus.timed_out
    assert job.result is None
    assert job.error == "execution exceeded timeout"
