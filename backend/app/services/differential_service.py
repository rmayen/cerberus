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
    """Run a baseline plus one variant per variation, comparing each to the
    baseline and recording observed behavioral dependencies with confidence."""
    if db.get(Sample, sample_id) is None:
        raise UnknownSample()

    analysis = DifferentialAnalysis(
        sample_id=sample_id,
        executor=executor_name,
        baseline_conditions=baseline_conditions,
        status=JobStatus.running,
        created_by=submitted_by,
    )
    db.add(analysis)
    db.flush()

    baseline_job = _run_variant(db, analysis, baseline_conditions, submitted_by, timeout_seconds)
    baseline_events = telemetry_service.list_events(db, baseline_job.id)

    for variation in variations:
        variant_conditions = {**baseline_conditions, **variation}
        variant_job = _run_variant(db, analysis, variant_conditions, submitted_by, timeout_seconds)
        variant_events = telemetry_service.list_events(db, variant_job.id)

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
