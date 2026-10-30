from datetime import UTC, datetime
from typing import Any, cast

from cryptography.fernet import InvalidToken
from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.analysis.attack import map_findings
from app.analysis.behavior import analyze
from app.executors.base import ExecutionResult
from app.executors.registry import UnknownExecutor, get_executor
from app.models import JOB_TRANSITIONS, AnalysisJob, JobStatus, Sample
from app.services import (
    attack_service,
    behavior_service,
    ioc_service,
    process_runner,
    telemetry_service,
)
from app.services.emergency_service import EmergencyStopActive, ensure_not_active
from app.storage import storage
from app.telemetry.normalizer import normalize


class JobError(Exception):
    pass


class UnknownSample(JobError):
    pass


class UnknownExecutorRequested(JobError):
    pass


def _transition(job: AnalysisJob, new: JobStatus) -> None:
    if new not in JOB_TRANSITIONS[job.status]:
        raise JobError(f"illegal transition {job.status} -> {new}")
    job.status = new


# Analysis state shown for a sample, from the status of its latest job. Cancelled jobs produced no
# result, so they leave the sample not analyzed.
ANALYSIS_STATE: dict[JobStatus, str] = {
    JobStatus.pending: "analyzing",
    JobStatus.running: "analyzing",
    JobStatus.completed: "analyzed",
    JobStatus.failed: "failed",
    JobStatus.timed_out: "failed",
    JobStatus.cancelled: "not_analyzed",
}


def analysis_states(db: Session, sample_ids: list[int]) -> dict[int, str]:
    """Analysis state for many samples in one query. The latest job is the highest job id.

    Samples with no jobs are absent from the result, so callers default them to not_analyzed.
    """
    if not sample_ids:
        return {}
    latest_ids = (
        select(func.max(AnalysisJob.id))
        .where(AnalysisJob.sample_id.in_(sample_ids))
        .group_by(AnalysisJob.sample_id)
    )
    rows = db.execute(
        select(AnalysisJob.sample_id, AnalysisJob.status).where(AnalysisJob.id.in_(latest_ids))
    ).all()
    return {sample_id: ANALYSIS_STATE[status] for sample_id, status in rows}


def get_job(db: Session, job_id: int) -> AnalysisJob | None:
    return db.get(AnalysisJob, job_id)


def list_jobs(
    db: Session, *, sample_id: int | None = None, status: JobStatus | None = None
) -> list[AnalysisJob]:
    stmt = select(AnalysisJob)
    if sample_id is not None:
        stmt = stmt.where(AnalysisJob.sample_id == sample_id)
    if status is not None:
        stmt = stmt.where(AnalysisJob.status == status)
    return list(db.execute(stmt.order_by(AnalysisJob.created_at.desc())).scalars())


def create_job(
    db: Session,
    *,
    sample_id: int,
    executor_name: str,
    conditions: dict[str, Any],
    submitted_by: int | None,
    timeout_seconds: int = 60,
) -> AnalysisJob:
    ensure_not_active(db)
    if db.get(Sample, sample_id) is None:
        raise UnknownSample()
    try:
        get_executor(executor_name)
    except UnknownExecutor as exc:
        raise UnknownExecutorRequested(executor_name) from exc

    job = AnalysisJob(
        sample_id=sample_id,
        executor=executor_name,
        conditions=conditions,
        submitted_by=submitted_by,
        timeout_seconds=timeout_seconds,
    )
    db.add(job)
    db.flush()
    db.commit()  # admitted: the record exists, and the admission lock is released
    return job


def _lease_held(db: Session, job: AnalysisJob, owner: str) -> bool:
    """True while this owner holds an unexpired lease. Locks the row until the transaction ends.

    An expired lease does not count, even before recovery has run, so a late worker cannot
    complete a job that recovery may already have failed.
    """
    row = db.execute(
        select(AnalysisJob.id)
        .where(
            AnalysisJob.id == job.id,
            AnalysisJob.status == JobStatus.running,
            AnalysisJob.lease_owner == owner,
            AnalysisJob.lease_expires_at > datetime.now(UTC),
        )
        .with_for_update()
    ).first()
    return row is not None


def _settle(
    db: Session,
    job: AnalysisJob,
    owner: str | None,
    status: JobStatus,
    *,
    error: str | None,
    result: ExecutionResult | None = None,
) -> AnalysisJob:
    """Write a job's terminal state and results, in one transaction.

    With a lease owner, the write happens only if the lease is still held. A worker that lost its
    lease discards its result, and whoever recovered the job keeps the status.
    """
    if owner is not None and not _lease_held(db, job, owner):
        db.rollback()
        return job
    _transition(job, status)
    job.error = error
    job.finished_at = datetime.now(UTC)
    if result is not None:
        job.result = result.observations
        job.duration_ms = result.duration_ms
    db.flush()
    if status == JobStatus.completed and result is not None:
        sample = db.get(Sample, job.sample_id)
        if sample is None:
            raise UnknownSample()
        events = normalize(result.observations)
        findings = analyze(events)
        telemetry_service.store(db, job.id, events)
        behavior_service.store(db, job.id, findings)
        attack_service.store(db, job.id, map_findings(findings))
        ioc_service.extract_and_store(
            db,
            sample_id=job.sample_id,
            job_id=job.id,
            sample_sha256=sample.sha256,
            events=events,
        )
    db.commit()  # persist the terminal state before any caller can roll back
    return job


def run_job(
    db: Session,
    job: AnalysisJob,
    *,
    timeout_seconds: int | None = None,
    owner: str | None = None,
    cancel: process_runner.CancelSignal | None = None,
) -> AnalysisJob:
    """Execute a job through its executor with a hard timeout and record the outcome.

    timeout_seconds=None uses the job's requested timeout. An explicit value overrides it.

    owner=None (inline): the job is admitted and started here, after the stop check.
    owner set (worker): the job must already be running under this lease owner. Every terminal
    write is applied only while that lease is still held.
    """
    sample = db.get(Sample, job.sample_id)
    if sample is None:
        raise UnknownSample()
    try:
        get_executor(job.executor)  # validates the executor name before any work starts
    except UnknownExecutor:
        if owner is None:
            raise
        # A worker must not crash on a job it cannot run. Record it failed, and let the next job
        # run. Otherwise one bad job would crash every worker that claims it.
        return _settle(db, job, owner, JobStatus.failed, error="executor is not available")
    timeout = job.timeout_seconds if timeout_seconds is None else timeout_seconds

    if owner is None:
        try:
            ensure_not_active(db)
        except EmergencyStopActive:
            # Never executed, so cancelled is accurate. The stop was activated after admission.
            _transition(job, JobStatus.cancelled)
            job.error = "emergency stop: job was not started"
            job.finished_at = datetime.now(UTC)
            db.commit()
            return job
        _transition(job, JobStatus.running)
        job.started_at = datetime.now(UTC)
        db.commit()  # release the start lock before execution

    try:
        storage.load(
            sample.sha256
        )  # the sample must still be readable; its bytes are not passed on
    except (OSError, InvalidToken):
        # Fixed message: OSError text contains the blob path, which must not reach clients.
        return _settle(db, job, owner, JobStatus.failed, error="sample data unavailable")

    outcome = process_runner.run_in_child(
        executor_name=job.executor,
        sample_sha256=sample.sha256,
        conditions=job.conditions,
        timeout_seconds=timeout,
        cancel=cancel,
    )
    if outcome.kind == "timed_out":
        return _settle(db, job, owner, JobStatus.timed_out, error=outcome.error)
    if outcome.kind == "cancelled":
        return _settle(db, job, owner, JobStatus.cancelled, error=outcome.error)
    if outcome.observations is None:
        return _settle(db, job, owner, JobStatus.failed, error=outcome.error)
    result = ExecutionResult(
        status="completed" if outcome.kind == "completed" else "failed",
        duration_ms=outcome.duration_ms,
        observations=outcome.observations,
        error=outcome.error,
    )
    status = JobStatus.completed if outcome.kind == "completed" else JobStatus.failed
    return _settle(db, job, owner, status, error=outcome.error, result=result)


def request_cancel_running(db: Session, job_id: int) -> tuple[AnalysisJob | None, str]:
    """Ask the worker to stop a running job. Returns (job, outcome).

    Outcomes: "requested" (set now), "already_requested", "not_running", or "not_found". The job
    stays running until its child process is confirmed stopped. Only then does it become cancelled.
    """
    job = db.get(AnalysisJob, job_id)
    if job is None:
        return None, "not_found"
    updated = cast(
        CursorResult[Any],
        db.execute(
            update(AnalysisJob)
            .where(
                AnalysisJob.id == job_id,
                AnalysisJob.status == JobStatus.running,
                AnalysisJob.cancel_requested.is_(False),
            )
            .values(cancel_requested=True)
            .execution_options(synchronize_session=False)
        ),
    ).rowcount
    db.commit()
    db.refresh(job)
    if updated == 1:
        return job, "requested"
    if job.status == JobStatus.running and job.cancel_requested:
        return job, "already_requested"
    return job, "not_running"


def cancel_queued(db: Session, job_id: int) -> tuple[AnalysisJob | None, str]:
    """Cancel a job only while it is still queued. Returns (job, outcome).

    Outcomes: "cancelled", "already_cancelled" (idempotent), "not_cancellable", or "not_found".
    The status check is part of the UPDATE, so it cannot race a worker claim: whichever commits
    first wins, and the loser sees the new status.
    """
    job = db.get(AnalysisJob, job_id)
    if job is None:
        return None, "not_found"
    if job.status == JobStatus.cancelled:
        return job, "already_cancelled"
    outcome_rows = cast(
        CursorResult[Any],
        db.execute(
            update(AnalysisJob)
            .where(AnalysisJob.id == job_id, AnalysisJob.status == JobStatus.pending)
            .values(
                status=JobStatus.cancelled,
                error="cancelled before start",
                finished_at=datetime.now(UTC),
            )
            .execution_options(synchronize_session=False)
        ),
    )
    updated = outcome_rows.rowcount
    if updated == 1:
        db.commit()
        db.refresh(job)
        return job, "cancelled"
    db.rollback()
    job = db.get(AnalysisJob, job_id)
    if job is not None and job.status == JobStatus.cancelled:
        return job, "already_cancelled"
    return job, "not_cancellable"
