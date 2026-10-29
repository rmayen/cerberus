from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_role
from app.models import Role, User
from app.schemas import DifferentialCreate, DifferentialRead
from app.services import audit, differential_service
from app.services.differential_service import UnknownSample

router = APIRouter(prefix="/api/v1/differential", tags=["differential"])


@router.post("", response_model=DifferentialRead, status_code=status.HTTP_201_CREATED)
def run_differential(
    body: DifferentialCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.analyst, Role.administrator)),
) -> object:
    try:
        analysis = differential_service.run_differential(
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

    audit.record(
        db,
        "differential_run",
        actor_user_id=user.id,
        detail=f"analysis {analysis.id} on sample {analysis.sample_id}: "
        f"{len(analysis.findings)} finding(s)",
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
