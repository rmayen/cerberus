"""Database-backed queue for simulated analysis jobs.

Lifecycle: pending (queued) -> running (claimed under a lease) -> completed, failed, or timed_out.
Queued jobs may be cancelled. A running job is kept alive by a heartbeat that renews its lease. If
the lease expires while the job is still running, recovery marks it failed as "outcome unknown".
It is never re-executed and never reported completed.

Guarantees, on PostgreSQL only:
- A pending job is claimed by exactly one worker (FOR UPDATE SKIP LOCKED).
- No claim starts while the emergency stop is active. Queued work stays pending for later.
- A cancellation and a claim of the same job cannot both succeed.
- A worker whose lease has expired or was recovered cannot write its result (see job_service).
SQLite has no row locks, so its results are best-effort only and must not be used for production.

Each running job executes in a child process. The heartbeat terminates that child when its lease
is lost, a cancel is requested, or the emergency stop is active. The emergency stop also blocks new
claims. A job is recorded cancelled or timed out only after its child process is verified stopped.
"""

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql import ColumnElement

from app.models import AnalysisJob, DifferentialAnalysis, JobStatus
from app.services import emergency_service, process_runner
from app.services.emergency_service import EmergencyStopActive, ensure_not_active
from app.services.job_service import _transition, run_job

RECOVERY_MESSAGE = "worker lease expired; outcome unknown, not re-executed"
LEASE_DURATION = timedelta(seconds=30)
HEARTBEAT_INTERVAL = timedelta(seconds=2)
# After a shutdown request, a running job may finish for this long. Then its child is terminated.
SHUTDOWN_GRACE_SECONDS = 15.0
SHUTDOWN_CANCEL_MESSAGE = "worker shutdown: execution terminated"

logger = logging.getLogger(__name__)


def _eligible() -> ColumnElement[bool]:
    """A differential variant may run only after its analysis's baseline has completed.

    The check reads committed rows. A baseline that completes commits before any variant can see
    it, and a failed baseline keeps its variants unclaimable until finalization cancels them.
    """
    baseline = aliased(AnalysisJob)
    completed_baseline = (
        select(baseline.id)
        .where(
            baseline.differential_id == AnalysisJob.differential_id,
            baseline.differential_role == "baseline",
            baseline.status == JobStatus.completed,
        )
        .exists()
    )
    return or_(
        AnalysisJob.differential_role.is_(None),
        AnalysisJob.differential_role == "baseline",
        completed_baseline,
    )


def claim_next(db: Session, *, owner: str, lease: timedelta = LEASE_DURATION) -> int | None:
    """Claim the oldest pending job for this owner. Returns its id, or None.

    One short transaction: check the stop, lock one pending row, record the lease, commit.
    """
    try:
        ensure_not_active(db)
    except EmergencyStopActive:
        db.rollback()  # queued work stays pending while the stop is active
        return None
    job = db.execute(
        select(AnalysisJob)
        .where(AnalysisJob.status == JobStatus.pending, _eligible())
        .order_by(AnalysisJob.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if job is None:
        db.commit()
        return None
    now = datetime.now(UTC)
    _transition(job, JobStatus.running)
    job.started_at = now
    job.lease_owner = owner
    job.lease_expires_at = now + lease
    if job.differential_id is not None:
        # Lock order matches differential cancel: the child is already locked, then the analysis.
        analysis = db.get(DifferentialAnalysis, job.differential_id, with_for_update=True)
        if analysis is not None and analysis.status == JobStatus.pending:
            analysis.status = JobStatus.running
    db.commit()
    return job.id


def renew_lease(db: Session, job_id: int, *, owner: str, lease: timedelta = LEASE_DURATION) -> bool:
    """Extend a live lease held by this owner. Returns False if the lease is gone.

    An expired lease is never renewed. Once it expires, only recovery may change the job.
    """
    now = datetime.now(UTC)
    result = cast(
        CursorResult[Any],
        db.execute(
            update(AnalysisJob)
            .where(
                AnalysisJob.id == job_id,
                AnalysisJob.status == JobStatus.running,
                AnalysisJob.lease_owner == owner,
                AnalysisJob.lease_expires_at > now,
            )
            .values(lease_expires_at=now + lease)
            .execution_options(synchronize_session=False)
        ),
    )
    renewed = result.rowcount == 1
    db.commit()
    return renewed


class LeaseHeartbeat:
    """Keeps a running job's lease alive and signals its child process to stop when needed.

    Each tick runs in its own session from session_factory, because the worker's session is busy
    running the job. A tick stops the child, through the CancelSignal, when:
    - the lease is no longer held (expired or recovered): the worker must not finish the job;
    - a cancel was requested for the job;
    - the emergency stop is active.
    A failed renewal query is logged and retried on the next tick. If the database stays
    unreachable, the lease expires and recovery marks the job failed.
    """

    def __init__(
        self,
        session_factory: Callable[[], Session],
        job_id: int,
        *,
        owner: str,
        lease: timedelta = LEASE_DURATION,
        interval: timedelta = HEARTBEAT_INTERVAL,
        cancel: process_runner.CancelSignal | None = None,
        shutdown: threading.Event | None = None,
        shutdown_grace: float = SHUTDOWN_GRACE_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._job_id = job_id
        self._owner = owner
        self._lease = lease
        self._interval = interval.total_seconds()
        self.cancel = cancel or process_runner.CancelSignal()
        self._shutdown = shutdown
        self._shutdown_grace = shutdown_grace
        self._shutdown_seen_at: float | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"heartbeat-{job_id}", daemon=True)

    def _tick(self) -> bool:
        """One heartbeat. Returns False when the thread should stop."""
        with self._session_factory() as session:
            if not renew_lease(session, self._job_id, owner=self._owner, lease=self._lease):
                self.cancel.set("worker lease was lost")
                return False
            if _cancel_requested(session, self._job_id):
                self.cancel.set("cancelled while running")
                return False
            if emergency_service.is_active(session):
                self.cancel.set("emergency stop: execution terminated")
                return False
        if self._shutdown is not None and self._shutdown.is_set():
            # The job may finish within the grace period. After it, the child is terminated.
            if self._shutdown_seen_at is None:
                self._shutdown_seen_at = time.monotonic()
            if time.monotonic() - self._shutdown_seen_at >= self._shutdown_grace:
                self.cancel.set(SHUTDOWN_CANCEL_MESSAGE)
                return False
        return True

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                if not self._tick():
                    return
            except SQLAlchemyError:
                logger.warning("heartbeat check failed for job %s; will retry", self._job_id)

    def __enter__(self) -> "LeaseHeartbeat":
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._stop.set()
        self._thread.join()


def _cancel_requested(session: Session, job_id: int) -> bool:
    return bool(
        session.execute(
            select(AnalysisJob.cancel_requested).where(AnalysisJob.id == job_id)
        ).scalar()
    )


def recover_expired_leases(db: Session, *, now: datetime | None = None) -> int:
    """Mark running jobs whose lease has expired as failed. Never re-executes them."""
    cutoff = now or datetime.now(UTC)
    jobs = list(
        db.execute(
            select(AnalysisJob)
            .where(
                AnalysisJob.status == JobStatus.running,
                AnalysisJob.lease_expires_at < cutoff,
            )
            .with_for_update(skip_locked=True)
        ).scalars()
    )
    for job in jobs:
        _transition(job, JobStatus.failed)
        job.error = RECOVERY_MESSAGE
        job.finished_at = cutoff
        job.lease_owner = None
    db.commit()
    return len(jobs)


def process_next(
    db: Session,
    *,
    owner: str,
    session_factory: Callable[[], Session] | None = None,
    shutdown: threading.Event | None = None,
) -> AnalysisJob | None:
    """Claim one queued job and execute it. Returns the job, or None if none was claimed.

    The job runs with its requested timeout. With a session_factory, a heartbeat keeps the lease
    alive for the whole run. Without one, no heartbeat runs and the lease lasts LEASE_DURATION
    only. The worker entrypoint always passes a factory. A shutdown event, once set, lets the
    running job finish for SHUTDOWN_GRACE_SECONDS before its child is terminated.
    """
    job_id = claim_next(db, owner=owner)
    if job_id is None:
        return None
    job = db.get(AnalysisJob, job_id)
    if job is None:
        return None
    if session_factory is None:
        return run_job(db, job, owner=owner)
    with LeaseHeartbeat(session_factory, job_id, owner=owner, shutdown=shutdown) as heartbeat:
        return run_job(db, job, owner=owner, cancel=heartbeat.cancel)


def drain(
    db: Session,
    *,
    owner: str,
    session_factory: Callable[[], Session] | None = None,
    shutdown: threading.Event | None = None,
) -> int:
    """Process queued jobs until none can be claimed or shutdown is requested.

    Returns how many were processed. Once shutdown is set, no new job is claimed.
    """
    processed = 0
    while not (shutdown is not None and shutdown.is_set()):
        if (
            process_next(db, owner=owner, session_factory=session_factory, shutdown=shutdown)
            is None
        ):
            break
        processed += 1
    return processed
