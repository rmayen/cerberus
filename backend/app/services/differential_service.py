"""Differential analyses, orchestrated through the job queue.

Creating an analysis queues one baseline job and one job per variation, all tagged with the
analysis. Workers run those jobs like any other queued job. A worker then finalizes the analysis
once every child job is terminal. Findings are produced only from completed children. If any child
failed, timed out, or was cancelled, the analysis fails and produces no findings or confidence.

Transactions are short. Nothing holds a database lock while a job executes.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.differential import compare
from app.executors.registry import UnknownExecutor, get_executor
from app.models import (
    AnalysisJob,
    Confidence,
    DifferentialAnalysis,
    DifferentialFinding,
    JobStatus,
    Sample,
)
from app.services import job_service, telemetry_service
from app.services.emergency_service import ensure_not_active

TERMINAL_JOB_STATES = frozenset(
    {JobStatus.completed, JobStatus.failed, JobStatus.timed_out, JobStatus.cancelled}
)
CANCELLED_MESSAGE = "cancelled before start"


class UnknownSample(Exception):
    pass


class UnknownExecutorRequested(Exception):
    pass


def get_analysis(db: Session, analysis_id: int) -> DifferentialAnalysis | None:
    return db.get(DifferentialAnalysis, analysis_id)


def list_analyses(db: Session, *, sample_id: int | None = None) -> list[DifferentialAnalysis]:
    stmt = select(DifferentialAnalysis)
    if sample_id is not None:
        stmt = stmt.where(DifferentialAnalysis.sample_id == sample_id)
    return list(db.execute(stmt.order_by(DifferentialAnalysis.created_at.desc())).scalars())


def enqueue(
    db: Session,
    *,
    sample_id: int,
    baseline_conditions: dict[str, Any],
    variations: list[dict[str, Any]],
    executor_name: str,
    submitted_by: int | None,
    timeout_seconds: int = 60,
) -> DifferentialAnalysis:
    """Record the analysis and queue its baseline and variant jobs in one transaction.

    Refused with EmergencyStopActive while the stop is active, before anything is written.
    """
    ensure_not_active(db)
    if db.get(Sample, sample_id) is None:
        raise UnknownSample()
    try:
        get_executor(executor_name)
    except UnknownExecutor as exc:
        raise UnknownExecutorRequested(executor_name) from exc

    analysis = DifferentialAnalysis(
        sample_id=sample_id,
        executor=executor_name,
        baseline_conditions=baseline_conditions,
        variations=variations,
        timeout_seconds=timeout_seconds,
        status=JobStatus.pending,
        created_by=submitted_by,
    )
    db.add(analysis)
    db.flush()
    db.add(
        AnalysisJob(
            sample_id=sample_id,
            executor=executor_name,
            conditions=baseline_conditions,
            submitted_by=submitted_by,
            timeout_seconds=timeout_seconds,
            differential_id=analysis.id,
            differential_role="baseline",
        )
    )
    for variation in variations:
        db.add(
            AnalysisJob(
                sample_id=sample_id,
                executor=executor_name,
                conditions={**baseline_conditions, **variation},
                submitted_by=submitted_by,
                timeout_seconds=timeout_seconds,
                differential_id=analysis.id,
                differential_role="variant",
                differential_variation=variation,
            )
        )
    db.commit()  # the whole analysis and its jobs are admitted together
    return analysis


def children(db: Session, analysis_id: int) -> list[AnalysisJob]:
    return list(
        db.execute(
            select(AnalysisJob)
            .where(AnalysisJob.differential_id == analysis_id)
            .order_by(AnalysisJob.id)
        ).scalars()
    )


def cancel(db: Session, analysis_id: int) -> tuple[DifferentialAnalysis | None, str]:
    """Cancel an analysis only while every child job is still queued. Returns (analysis, outcome).

    Outcomes: "cancelled", "already_cancelled", "not_cancellable", or "not_found".
    Lock order matches worker claims: child jobs first, then the analysis. A claim that already
    holds a child makes this wait, then it sees the job running and refuses. A claim that starts
    later skips the locked rows. Neither order can deadlock.
    """
    if db.get(DifferentialAnalysis, analysis_id) is None:
        db.rollback()
        return None, "not_found"
    jobs = list(
        db.execute(
            select(AnalysisJob)
            .where(AnalysisJob.differential_id == analysis_id)
            .order_by(AnalysisJob.id)
            .with_for_update()
        ).scalars()
    )
    analysis = db.execute(
        select(DifferentialAnalysis).where(DifferentialAnalysis.id == analysis_id).with_for_update()
    ).scalar_one()
    if analysis.status == JobStatus.cancelled:
        db.rollback()
        return analysis, "already_cancelled"
    if analysis.status not in (JobStatus.pending, JobStatus.running):
        db.rollback()
        return analysis, "not_cancellable"
    if not jobs or any(job.status != JobStatus.pending for job in jobs):
        db.rollback()
        return analysis, "not_cancellable"

    now = datetime.now(UTC)
    for job in jobs:
        job_service._transition(job, JobStatus.cancelled)
        job.error = CANCELLED_MESSAGE
        job.finished_at = now
    analysis.status = JobStatus.cancelled
    analysis.error_message = CANCELLED_MESSAGE
    analysis.finished_at = now
    db.commit()
    return analysis, "cancelled"


def finalize_ready(db: Session, *, limit: int = 20) -> int:
    """Finalize analyses whose child jobs are all terminal. Returns how many were finalized.

    Each analysis is locked (skipping any locked by another worker), so finalization runs once.
    The result is committed as a whole, or not at all.
    """
    analyses = list(
        db.execute(
            select(DifferentialAnalysis)
            .where(DifferentialAnalysis.status.in_([JobStatus.pending, JobStatus.running]))
            .order_by(DifferentialAnalysis.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).scalars()
    )
    finalized = 0
    for analysis in analyses:
        jobs = children(db, analysis.id)
        baseline = next((job for job in jobs if job.differential_role == "baseline"), None)
        if baseline is not None and baseline.status in TERMINAL_JOB_STATES:
            if baseline.status != JobStatus.completed:
                _cancel_unstarted_variants(db, jobs)  # variants never run after a failed baseline
        if not jobs or any(job.status not in TERMINAL_JOB_STATES for job in jobs):
            continue
        _finalize(db, analysis, jobs)
        finalized += 1
    db.commit()
    return finalized


def _cancel_unstarted_variants(db: Session, jobs: list[AnalysisJob]) -> None:
    """Cancel variants that were never claimed because their baseline did not complete."""
    now = datetime.now(UTC)
    for job in jobs:
        if job.differential_role == "variant" and job.status == JobStatus.pending:
            job_service._transition(job, JobStatus.cancelled)
            job.error = "not run: baseline did not complete"
            job.finished_at = now
    db.flush()


def _finalize(db: Session, analysis: DifferentialAnalysis, jobs: list[AnalysisJob]) -> None:
    baseline = next((job for job in jobs if job.differential_role == "baseline"), None)
    failed = [job for job in jobs if job.status != JobStatus.completed]
    if baseline is None or failed:
        culprit = failed[0] if failed else None
        label = "Variant" if culprit and culprit.differential_role == "variant" else "Baseline"
        verb = {
            JobStatus.timed_out: "timed out",
            JobStatus.cancelled: "was cancelled",
        }.get(culprit.status if culprit else JobStatus.failed, "failed")
        analysis.status = JobStatus.failed
        analysis.error_message = f"{label} run {verb}. The other runs were not compared."
        analysis.finished_at = datetime.now(UTC)
        db.flush()
        return

    baseline_events = telemetry_service.list_events(db, baseline.id)
    for variant in (job for job in jobs if job.differential_role == "variant"):
        variant_events = telemetry_service.list_events(db, variant.id)
        for axis, variant_value in (variant.differential_variation or {}).items():
            result = compare(
                axis,
                baseline.conditions.get(axis),
                variant_value,
                baseline_events,
                variant_events,
            )
            if result is not None:
                db.add(
                    DifferentialFinding(
                        analysis_id=analysis.id,
                        axis=axis,
                        baseline_value=baseline.conditions.get(axis),
                        variant_value=variant_value,
                        summary=result.summary,
                        confidence=Confidence(result.confidence),
                        added=result.added,
                        removed=result.removed,
                    )
                )
    analysis.status = JobStatus.completed
    analysis.finished_at = datetime.now(UTC)
    db.flush()
