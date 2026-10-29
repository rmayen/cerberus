from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models import EmergencyStop, utcnow

STOP_ROW_ID = 1


class EmergencyStopActive(Exception):
    """Raised when new work is requested while the emergency stop is on."""


def _switch_query(*, exclusive: bool) -> Select[Any]:
    """Locking read of the switch row.

    On PostgreSQL, FOR SHARE lets admissions run alongside each other. FOR UPDATE makes an
    activation wait for in-flight admissions, and blocks new ones until it commits. Databases
    without row locks ignore the clause, so the guarantee is weaker there.
    """
    stmt = (
        select(EmergencyStop)
        .where(EmergencyStop.id == STOP_ROW_ID)
        .execution_options(populate_existing=True)
    )
    return stmt.with_for_update(read=not exclusive)


def is_active(db: Session) -> bool:
    row = db.get(EmergencyStop, STOP_ROW_ID)
    return row is not None and row.active


def ensure_not_active(db: Session) -> None:
    """Admission check. Holds a shared row lock until the caller's transaction ends, so the caller
    must commit promptly and must not hold it while analysis executes."""
    row = db.execute(_switch_query(exclusive=False)).scalar_one_or_none()
    if row is not None and row.active:
        raise EmergencyStopActive()


def set_active(db: Session, *, active: bool, actor_id: int) -> bool:
    row = db.execute(_switch_query(exclusive=True)).scalar_one_or_none()
    if row is None:
        row = EmergencyStop(id=STOP_ROW_ID, active=False)
        db.add(row)
    row.active = active
    row.changed_by = actor_id
    row.changed_at = utcnow()
    db.flush()
    return row.active
