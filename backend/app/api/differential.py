from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_role
from app.models import Role, User
from app.schemas import DifferentialCreate, DifferentialRead
from app.services import audit, differential_service
from app.services.differential_service import UnknownExecutorRequested, UnknownSample
from app.services.emergency_service import EmergencyStopActive

router = APIRouter(prefix="/api/v1/differential", tags=["differential"])


@router.post("", response_model=DifferentialRead, status_code=status.HTTP_201_CREATED)
def run_differential(
    body: DifferentialCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.analyst, Role.administrator)),
) -> object:
    try:
        analysis = differential_service.enqueue(
            db,
            sample_id=body.sample_id,
            baseline_conditions=body.baseline_conditions,
            variations=body.variations,
            executor_name=body.executor,
            submitted_by=user.id,
            timeout_seconds=body.timeout_seconds,
        )
    except UnknownSample as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "sample not found") from exc
    except UnknownExecutorRequested as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown executor: {exc}") from exc
    except EmergencyStopActive as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "emergency stop is active; new analysis is disabled",
        ) from exc

    audit.record(
        db,
        "differential_queued",
        actor_user_id=user.id,
        detail=f"analysis {analysis.id} on sample {analysis.sample_id} queued",
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return analysis


@router.post("/{analysis_id}/cancel", response_model=DifferentialRead)
def cancel_analysis(
    analysis_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.analyst, Role.administrator)),
) -> object:
    """Cancel an analysis whose runs have not started. Idempotent. Otherwise 409."""
    existing = differential_service.get_analysis(db, analysis_id)
    if existing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "analysis not found")
    if user.role != Role.administrator and existing.created_by != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "only the submitter or an administrator can cancel"
        )
    analysis, outcome = differential_service.cancel(db, analysis_id)
    if outcome == "not_found" or analysis is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "analysis not found")
    if outcome == "not_cancellable":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"analysis is {analysis.status}; only analyses whose runs have not started can be "
            "cancelled",
        )
    if outcome == "cancelled":
        audit.record(
            db,
            "differential_cancelled",
            actor_user_id=user.id,
            detail=f"analysis {analysis.id} cancelled before start",
            ip=request.client.host if request.client else None,
        )
        db.commit()
    return analysis


@router.get("", response_model=list[DifferentialRead])
def list_analyses(
    sample_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.viewer, Role.analyst, Role.administrator)),
) -> object:
    return differential_service.list_analyses(db, sample_id=sample_id)


@router.get("/{analysis_id}", response_model=DifferentialRead)
def get_analysis(
    analysis_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.viewer, Role.analyst, Role.administrator)),
) -> object:
    analysis = differential_service.get_analysis(db, analysis_id)
    if analysis is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "analysis not found")
    return analysis
