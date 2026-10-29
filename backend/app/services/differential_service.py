from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.differential import compare
from app.models import (
    AnalysisJob,
    Confidence,
    DifferentialAnalysis,
    DifferentialFinding,
    JobStatus,
    Sample,
)
from app.services import job_service, telemetry_service
from app.services.emergency_service import EmergencyStopActive, ensure_not_active


class UnknownSample(Exception):
    pass


def get_analysis(db: Session, analysis_id: int) -> DifferentialAnalysis | None:
    return db.get(DifferentialAnalysis, analysis_id)


def list_analyses(db: Session, *, sample_id: int | None = None) -> list[DifferentialAnalysis]:
    stmt = select(DifferentialAnalysis)
    if sample_id is not None:
        stmt = stmt.where(DifferentialAnalysis.sample_id == sample_id)
    return list(db.execute(stmt.order_by(DifferentialAnalysis.created_at.desc())).scalars())


def _run_variant(
    db: Session,
    analysis: DifferentialAnalysis,
    conditions: dict[str, Any],
    submitted_by: int | None,
    timeout_seconds: int,
) -> AnalysisJob:
    job = job_service.create_job(
        db,
        sample_id=analysis.sample_id,
        executor_name=analysis.executor,
        conditions=conditions,
        submitted_by=submitted_by,
    )
    job.differential_id = analysis.id
    job_service.run_job(db, job, timeout_seconds=timeout_seconds)
    return job


def _job_unsuccessful(
    db: Session, analysis: DifferentialAnalysis, job: AnalysisJob, label: str
) -> bool:
    """Fail the analysis if a run did not complete. The job record itself is kept unchanged.

    The stored message is fixed text built from the run label and outcome. It never includes
    job.error, which can contain internal paths.
    """
    if job.status == JobStatus.completed:
        return False
    if job.status == JobStatus.cancelled:
        verb = "was not started (emergency stop)"
    elif job.status == JobStatus.timed_out:
        verb = "timed out"
    else:
        verb = "failed"
    analysis.status = JobStatus.failed
    analysis.error_message = f"{label} run {verb}. The other runs were not compared."
    analysis.finished_at = datetime.now(UTC)
    db.flush()
    return True


EMERGENCY_MID_RUN = (
    "Emergency stop was activated during this analysis. Runs not yet started were skipped, "
    "so no comparison was made."
)


def run_differential(
    db: Session,
    *,
    sample_id: int,
    baseline_conditions: dict[str, Any],
    variations: list[dict[str, Any]],
    executor_name: str,
    submitted_by: int | None,
    timeout_seconds: int = 60,
) -> DifferentialAnalysis:
    """Run a baseline plus one variant per variation, comparing each to the baseline and
    recording observed behavioral dependencies with confidence.

    A refusal before the analysis is committed creates no records. A refusal after that marks the
    analysis failed. Runs that already completed stay recorded.
    """
    if db.get(Sample, sample_id) is None:
        raise UnknownSample()
    ensure_not_active(db)

    analysis = DifferentialAnalysis(
        sample_id=sample_id,
        executor=executor_name,
        baseline_conditions=baseline_conditions,
        status=JobStatus.running,
        created_by=submitted_by,
    )
    db.add(analysis)
    db.commit()  # admitted; release the admission lock before any run executes
    try:
        result = _run_admitted(
            db,
            analysis,
            baseline_conditions=baseline_conditions,
            variations=variations,
            submitted_by=submitted_by,
            timeout_seconds=timeout_seconds,
        )
        db.commit()  # persist outcome, findings, and job states together
        return result
    except EmergencyStopActive:
        db.rollback()
        analysis.status = JobStatus.failed
        analysis.error_message = EMERGENCY_MID_RUN
        analysis.finished_at = datetime.now(UTC)
        db.commit()
        return analysis


def _run_admitted(
    db: Session,
    analysis: DifferentialAnalysis,
    *,
    baseline_conditions: dict[str, Any],
    variations: list[dict[str, Any]],
    submitted_by: int | None,
    timeout_seconds: int,
) -> DifferentialAnalysis:
    # Run every job before comparing anything. If any job did not complete, the analysis fails and
    # no comparison or finding is produced from partial results.
    baseline_job = _run_variant(db, analysis, baseline_conditions, submitted_by, timeout_seconds)
    if _job_unsuccessful(db, analysis, baseline_job, "Baseline"):
        return analysis
    baseline_events = telemetry_service.list_events(db, baseline_job.id)

    runs: list[tuple[dict[str, Any], list[Any]]] = []
    for variation in variations:
        variant_conditions = {**baseline_conditions, **variation}
        variant_job = _run_variant(db, analysis, variant_conditions, submitted_by, timeout_seconds)
        if _job_unsuccessful(db, analysis, variant_job, "Variant"):
            return analysis
        runs.append((variation, telemetry_service.list_events(db, variant_job.id)))

    for variation, variant_events in runs:
        for axis, variant_value in variation.items():
            result = compare(
                axis,
                baseline_conditions.get(axis),
                variant_value,
                baseline_events,
                variant_events,
            )
            if result is not None:
                db.add(
                    DifferentialFinding(
                        analysis_id=analysis.id,
                        axis=axis,
                        baseline_value=baseline_conditions.get(axis),
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
    return analysis
