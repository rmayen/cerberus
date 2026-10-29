from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_role
from app.models import Role, User
from app.schemas import CaseCreate, CaseRead
from app.services import audit, case_service
from app.services.case_service import CaseAlreadyExists

router = APIRouter(prefix="/api/v1/cases", tags=["cases"])


@router.post("", response_model=CaseRead, status_code=status.HTTP_201_CREATED)
def create_case(
    body: CaseCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.analyst, Role.administrator)),
) -> object:
    try:
        case = case_service.create_case(db, body.name, body.description, user.id)
    except CaseAlreadyExists as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "case name already exists") from exc
    audit.record(
        db,
        "case_created",
        actor_user_id=user.id,
        detail=f"case {case.name!r}",
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return case


@router.get("", response_model=list[CaseRead])
def list_cases(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.viewer, Role.analyst, Role.administrator)),
) -> object:
    return case_service.list_cases(db)
