# ruff: noqa: F811  (pytest fixtures are imported from another test module)
"""Worker shutdown, crash recovery, supervisor restarts, readiness, and orphaned children.

Uses harmless fixture executors only (tests/executor_fixtures.py). Nothing here runs sample bytes.
"""

import json
import os
import subprocess
import sys
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest

from app import supervisor, worker
from app.models import AnalysisJob, JobStatus, Sample
from app.services import job_service, process_runner
from app.services.worker_service import (
    RECOVERY_MESSAGE,
    SHUTDOWN_CANCEL_MESSAGE,
    LeaseHeartbeat,
    claim_next,
    drain,
    process_next,
    recover_expired_leases,
)
from tests.test_executor_process import _claimed_job, file_db, storage_ok  # noqa: F401


def _queued_job(factory, executor: str, conditions: dict) -> int:  # type: ignore[no-untyped-def]
    with factory() as db:
        sample = Sample(
            sha256="e" * 64, filename="w.bin", size_bytes=2, detected_type="pe", stored_path="u"
        )
        db.add(sample)
        db.commit()
        return job_service.create_job(
            db,
            sample_id=sample.id,
            executor_name=executor,
            conditions=conditions,
            submitted_by=None,
        ).id


def _status(factory, job_id: int) -> tuple[JobStatus, str | None]:  # type: ignore[no-untyped-def]
    with factory() as db:
        job = db.get(AnalysisJob, job_id)
        return job.status, job.error


# --- clean shutdown -------------------------------------------------------------------------


def test_shutdown_stops_new_claims(file_db, storage_ok: None) -> None:  # type: ignore[no-untyped-def]
    job_id = _queued_job(file_db, "simulated", {})
    stop = threading.Event()
    stop.set()
    with file_db() as db:
        assert drain(db, owner="w1", session_factory=file_db, shutdown=stop) == 0
    assert _status(file_db, job_id) == (JobStatus.pending, None)


def test_job_finishing_within_the_grace_period_completes(file_db, storage_ok: None) -> None:  # type: ignore[no-untyped-def]
    job_id = _queued_job(file_db, "simulated", {})
    stop = threading.Event()
    stop.set()  # shutdown requested while the job runs; it is quick enough to finish in the grace
    with file_db() as db:
        assert process_next(db, owner="w1", session_factory=file_db, shutdown=stop) is not None
    assert _status(file_db, job_id) == (JobStatus.completed, None)


def test_shutdown_terminates_a_running_child_after_the_grace_period(
    file_db,  # type: ignore[no-untyped-def]
    storage_ok: None,
) -> None:
    job_id = _claimed_job(file_db, "hanging", "w1", timedelta(seconds=30))
    stop = threading.Event()
    stop.set()
    with file_db() as db:
        job = db.get(AnalysisJob, job_id)
        with LeaseHeartbeat(
            file_db,
            job_id,
            owner="w1",
            interval=timedelta(milliseconds=20),
            shutdown=stop,
            shutdown_grace=0.2,
        ) as heartbeat:
            job_service.run_job(db, job, owner="w1", cancel=heartbeat.cancel)
    assert _status(file_db, job_id) == (JobStatus.cancelled, SHUTDOWN_CANCEL_MESSAGE)


# --- crash recovery -------------------------------------------------------------------------


def test_abandoned_job_is_failed_and_never_rerun_after_a_crash(
    file_db,  # type: ignore[no-untyped-def]
    storage_ok: None,
    tmp_path: Path,
) -> None:
    log = tmp_path / "runs.log"
    job_id = _queued_job(file_db, "scripted", {"log": str(log)})
    with file_db() as db:
        assert claim_next(db, owner="dead-worker", lease=timedelta(seconds=-1)) == job_id
    with file_db() as db:
        assert recover_expired_leases(db) == 1
    with file_db() as db:
        assert drain(db, owner="new-worker", session_factory=file_db) == 0
    assert _status(file_db, job_id) == (JobStatus.failed, RECOVERY_MESSAGE)
    assert not log.exists()  # the abandoned job never reached an executor again


def test_recovery_after_a_restart_runs_queued_work_normally(
    file_db,  # type: ignore[no-untyped-def]
    storage_ok: None,
) -> None:
    abandoned = _claimed_job(file_db, "simulated", "dead-worker", timedelta(seconds=-1))
    queued = _queued_job(file_db, "simulated", {})
    with file_db() as db:
        recover_expired_leases(db)
        assert drain(db, owner="new-worker", session_factory=file_db) == 1
    assert _status(file_db, abandoned)[0] == JobStatus.failed
    assert _status(file_db, queued) == (JobStatus.completed, None)


def test_job_with_an_unavailable_executor_fails_without_crashing_the_worker(
    file_db,  # type: ignore[no-untyped-def]
    storage_ok: None,
) -> None:
    with file_db() as db:
        sample = Sample(
            sha256="d" * 64, filename="x.bin", size_bytes=2, detected_type="pe", stored_path="u"
        )
        db.add(sample)
        db.commit()
        # Created directly: create_job would refuse an executor the worker does not have.
        job = AnalysisJob(sample_id=sample.id, executor="removed-executor", conditions={})
        db.add(job)
        db.commit()
        job_id = job.id
    with file_db() as db:
        assert process_next(db, owner="w1", session_factory=file_db) is not None
    assert _status(file_db, job_id) == (JobStatus.failed, "executor is not available")


# --- supervisor -----------------------------------------------------------------------------


def test_supervisor_stops_restarting_at_the_crash_loop_breaker(tmp_path: Path) -> None:
    starts = tmp_path / "starts.log"
    command = [
        sys.executable,
        "-c",
        f"open({str(starts)!r}, 'a').write('x\\n'); import sys; sys.exit(3)",
    ]
    status = supervisor.supervise(
        command,
        stop=threading.Event(),
        max_restarts=2,
        window=60,
        backoff=lambda crashes: 0,
        cwd=tmp_path,
    )
    assert status == 1
    assert starts.read_text().count("x") == 3  # first start plus two restarts, then it gives up


def test_supervisor_terminates_the_worker_when_stop_is_requested(tmp_path: Path) -> None:
    event = threading.Event()
    threading.Timer(0.5, event.set).start()
    started = time.monotonic()
    status = supervisor.supervise(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stop=event,
        stop_grace=5,
        cwd=tmp_path,
    )
    assert status == 0
    assert time.monotonic() - started < 10


def test_supervisor_does_not_restart_after_stop_during_backoff(tmp_path: Path) -> None:
    starts = tmp_path / "starts.log"
    command = [
        sys.executable,
        "-c",
        f"open({str(starts)!r}, 'a').write('x\\n'); import sys; sys.exit(3)",
    ]
    event = threading.Event()
    threading.Timer(1.0, event.set).start()
    status = supervisor.supervise(command, stop=event, backoff=lambda crashes: 60, cwd=tmp_path)
    assert status == 0
    assert starts.read_text().count("x") == 1  # the backoff was cut short, no second start


def test_backoff_doubles_and_is_capped() -> None:
    assert [supervisor.backoff_seconds(n) for n in (1, 2, 3)] == [1.0, 2.0, 4.0]
    assert supervisor.backoff_seconds(50) == supervisor.BACKOFF_MAX_SECONDS


# --- readiness ------------------------------------------------------------------------------


def test_readiness_requires_a_ready_state_and_a_live_process(tmp_path: Path) -> None:
    path = tmp_path / "status.json"
    assert worker.check_status(path) is False  # no file

    worker.write_status(worker.STATE_READY, path)
    assert worker.check_status(path) is True

    worker.write_status(worker.STATE_STOPPING, path)
    assert worker.check_status(path) is False

    path.write_text("[]")
    assert worker.check_status(path) is False

    path.write_text(json.dumps({"state": "ready", "pid": 2**22 + 1, "updated_at": "x"}))
    if os.name == "posix":
        assert worker.check_status(path) is False  # a crashed worker leaves ready behind


# --- orphaned children (POSIX) --------------------------------------------------------------


@pytest.mark.skipif(os.name != "posix", reason="parent-liveness watchdog is POSIX only")
def test_child_exits_when_its_worker_dies(tmp_path: Path) -> None:
    # An intermediate process starts a hanging child and exits at once, so the child is re-parented
    # while it is still starting. The request names the intermediate as its worker.
    intermediate = f"""
import json, os, subprocess, sys
request = json.dumps({{
    "executor": "hanging",
    "sample_sha256": "f" * 64,
    "conditions": {{}},
    "timeout_seconds": 60,
    "parent_pid": os.getpid(),
}}).encode()
child = subprocess.Popen(
    [sys.executable, "-m", "app.executors.child"],
    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    cwd={str(process_runner.BACKEND_ROOT)!r},
)
child.stdin.write(request)
child.stdin.close()
print(child.pid, flush=True)
"""
    out = subprocess.run(
        [sys.executable, "-c", intermediate], capture_output=True, text=True, check=True
    )
    child_pid = int(out.stdout.strip())

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            return  # the orphan stopped itself
        time.sleep(0.2)
    pytest.fail("orphaned child kept running after its worker died")
