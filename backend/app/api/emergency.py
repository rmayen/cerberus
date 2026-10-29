from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_role
from app.models import Role, User
from app.schemas import EmergencyStopRead, EmergencyStopUpdate
from app.services import audit, emergency_service

router = APIRouter(prefix="/api/v1/emergency-stop", tags=["emergency-stop"])


@router.get("", response_model=EmergencyStopRead)
def read_emergency_stop(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.viewer, Role.analyst, Role.administrator)),
) -> EmergencyStopRead:
    return EmergencyStopRead(active=emergency_service.is_active(db))


@router.put("", response_model=EmergencyStopRead, status_code=status.HTTP_200_OK)
def set_emergency_stop(
    body: EmergencyStopUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(Role.administrator)),
) -> EmergencyStopRead:
    active = emergency_service.set_active(db, active=body.active, actor_id=admin.id)
    audit.record(
        db,
        "emergency_stop_set",
        actor_user_id=admin.id,
        detail=f"emergency stop active={active}",
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return EmergencyStopRead(active=active)
