from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_role
from app.models import JobStatus, Role, TelemetryCategory, User
from app.schemas import AttackMappingRead, FindingRead, JobCreate, JobRead, TelemetryEventRead
from app.services import (
    attack_service,
    audit,
    behavior_service,
    job_service,
    report_service,
    telemetry_service,
)
from app.services.job_service import UnknownExecutorRequested, UnknownSample

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def submit_job(
    body: JobCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.analyst, Role.administrator)),
) -> object:
    try:
        job = job_service.create_job(
            db,
            sample_id=body.sample_id,
            executor_name=body.executor,
            conditions=body.conditions,
            submitted_by=user.id,
        )
    except UnknownSample as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "sample not found") from exc
    except UnknownExecutorRequested as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown executor: {exc}") from exc

    job_service.run_job(db, job, timeout_seconds=body.timeout_seconds)
    audit.record(
        db,
        "job_run",
        actor_user_id=user.id,
        detail=f"job {job.id} on sample {job.sample_id}: {job.status}",
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return job


@router.get("", response_model=list[JobRead])
def list_jobs(
    sample_id: int | None = None,
    status_filter: JobStatus | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.viewer, Role.analyst, Role.administrator)),
) -> object:
    return job_service.list_jobs(db, sample_id=sample_id, status=status_filter)


@router.get("/{job_id}", response_model=JobRead)
def get_job(
    job_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.viewer, Role.analyst, Role.administrator)),
) -> object:
    job = job_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return job


@router.get("/{job_id}/telemetry", response_model=list[TelemetryEventRead])
def job_telemetry(
    job_id: int,
    category: TelemetryCategory | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.viewer, Role.analyst, Role.administrator)),
) -> object:
    if job_service.get_job(db, job_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return telemetry_service.list_events(db, job_id, category=category)


@router.get("/{job_id}/findings", response_model=list[FindingRead])
def job_findings(
    job_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.viewer, Role.analyst, Role.administrator)),
) -> object:
    if job_service.get_job(db, job_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return behavior_service.list_findings(db, job_id)


@router.get("/{job_id}/attack", response_model=list[AttackMappingRead])
def job_attack(
    job_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.viewer, Role.analyst, Role.administrator)),
) -> object:
    if job_service.get_job(db, job_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return attack_service.list_mappings(db, job_id)


@router.get("/{job_id}/report")
def job_report(
    job_id: int,
    format: str = "html",
    notes: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.viewer, Role.analyst, Role.administrator)),
) -> Response:
    job = job_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")

    if format == "html":
        return HTMLResponse(report_service.render_html(db, job, notes))
    if format == "pdf":
        return Response(
            content=report_service.render_pdf(db, job, notes),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="report_{job_id}.pdf"'},
        )
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "format must be html or pdf")
