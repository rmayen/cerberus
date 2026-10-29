from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis.attack import map_findings
from app.analysis.behavior import analyze
from app.executors.base import ExecutionRequest, Executor
from app.executors.registry import UnknownExecutor, get_executor
from app.models import JOB_TRANSITIONS, AnalysisJob, JobStatus, Sample
from app.services import attack_service, behavior_service, ioc_service, telemetry_service
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
) -> AnalysisJob:
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
    )
    db.add(job)
    db.flush()
    return job


def run_job(db: Session, job: AnalysisJob, *, timeout_seconds: int = 60) -> AnalysisJob:
    """Execute a pending job through its executor with a hard timeout, recording
    the outcome and enforcing safe state transitions."""
    sample = db.get(Sample, job.sample_id)
    if sample is None:
        raise UnknownSample()
    executor: Executor = get_executor(job.executor)

    _transition(job, JobStatus.running)
    job.started_at = datetime.now(UTC)
    db.flush()

    request = ExecutionRequest(
        sample_sha256=sample.sha256,
        data=storage.load(sample.sha256),
        conditions=job.conditions,
        timeout_seconds=timeout_seconds,
    )

    # Not a `with` block: exiting one waits for the worker thread, so a hung executor would block
    # the request. shutdown(wait=False) returns at once. Python cannot stop the thread, so a
    # timed-out executor keeps running in the background. Its result is discarded, and only this
    # function writes the job, so a late result cannot change the recorded status.
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(executor.run, request)
        result = future.result(timeout=timeout_seconds)
    except TimeoutError:
        _transition(job, JobStatus.timed_out)
        job.error = "execution exceeded timeout"
        job.finished_at = datetime.now(UTC)
        db.flush()
        return job
    except Exception as exc:  # executor raised
        _transition(job, JobStatus.failed)
        job.error = str(exc)
        job.finished_at = datetime.now(UTC)
        db.flush()
        return job
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    _transition(job, JobStatus.completed if result.status == "completed" else JobStatus.failed)
    job.result = result.observations
    job.error = result.error
    job.duration_ms = result.duration_ms
    job.finished_at = datetime.now(UTC)
    db.flush()

    if job.status == JobStatus.completed:
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
        db.flush()
    return job
