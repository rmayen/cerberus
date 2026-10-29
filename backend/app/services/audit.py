from sqlalchemy.orm import Session

from app.models import AuditLog


def record(
    db: Session,
    action: str,
    *,
    actor_user_id: int | None = None,
    detail: str | None = None,
    ip: str | None = None,
) -> None:
    """Append a security-relevant event to the audit log. Caller commits."""
    db.add(AuditLog(action=action, actor_user_id=actor_user_id, detail=detail, ip=ip))
