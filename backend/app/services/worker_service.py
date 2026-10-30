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

Running work cannot be terminated. The emergency stop blocks new claims but does not stop a job
that is already executing.
"""

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import AnalysisJob, JobStatus
from app.services.emergency_service import EmergencyStopActive, ensure_not_active
from app.services.job_service import _transition, run_job

RECOVERY_MESSAGE = "worker lease expired; outcome unknown, not re-executed"
LEASE_DURATION = timedelta(seconds=30)
HEARTBEAT_INTERVAL = timedelta(seconds=10)

logger = logging.getLogger(__name__)


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
        .where(AnalysisJob.status == JobStatus.pending)
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
    """Renews a job's lease from a background thread while the job executes.

    The thread uses its own session from session_factory, because the worker's session is busy
    running the job. The thread stops when the context exits, or when a renewal finds the lease
    gone. A failed renewal is logged and retried on the next tick. If renewals keep failing, the
    lease expires and recovery marks the job failed.
    """

    def __init__(
        self,
        session_factory: Callable[[], Session],
        job_id: int,
        *,
        owner: str,
        lease: timedelta = LEASE_DURATION,
        interval: timedelta = HEARTBEAT_INTERVAL,
    ) -> None:
        self._session_factory = session_factory
        self._job_id = job_id
        self._owner = owner
        self._lease = lease
        self._interval = interval.total_seconds()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"heartbeat-{job_id}", daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                with self._session_factory() as session:
                    renewed = renew_lease(
                        session, self._job_id, owner=self._owner, lease=self._lease
                    )
            except SQLAlchemyError:
                logger.warning("lease renewal failed for job %s; will retry", self._job_id)
                continue
            if not renewed:
                logger.warning(
                    "lease for job %s is no longer held; heartbeat stopped", self._job_id
                )
                return

    def __enter__(self) -> "LeaseHeartbeat":
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._stop.set()
        self._thread.join()


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
) -> AnalysisJob | None:
    """Claim one queued job and execute it. Returns the job, or None if none was claimed.

    The job runs with its requested timeout. With a session_factory, a heartbeat keeps the lease
    alive for the whole run. Without one, no heartbeat runs and the lease lasts LEASE_DURATION
    only. The worker entrypoint always passes a factory.
    """
    job_id = claim_next(db, owner=owner)
    if job_id is None:
        return None
    job = db.get(AnalysisJob, job_id)
    if job is None:
        return None
    if session_factory is None:
        return run_job(db, job, owner=owner)
    with LeaseHeartbeat(session_factory, job_id, owner=owner):
        return run_job(db, job, owner=owner)


def drain(
    db: Session,
    *,
    owner: str,
    session_factory: Callable[[], Session] | None = None,
) -> int:
    """Process queued jobs until none can be claimed. Returns how many were processed."""
    processed = 0
    while process_next(db, owner=owner, session_factory=session_factory) is not None:
        processed += 1
    return processed
