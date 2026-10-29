from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_role
from app.models import Role, User
from app.schemas import UserCreate, UserRead
from app.services import audit, user_service
from app.services.user_service import UserAlreadyExists

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(Role.administrator)),
) -> User:
    try:
        user = user_service.create_user(db, body.username, body.password, body.role)
    except UserAlreadyExists as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "username already exists") from exc
    audit.record(
        db,
        "user_created",
        actor_user_id=admin.id,
        detail=f"created {user.username!r} as {user.role.value}",
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return user


@router.get("", response_model=list[UserRead])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.administrator, Role.analyst)),
) -> list[User]:
    return user_service.list_users(db)
