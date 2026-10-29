from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TelemetryCategory, TelemetryEvent
from app.telemetry.normalizer import NormalizedEvent


def store(db: Session, job_id: int, events: list[NormalizedEvent]) -> int:
    """Persist normalized telemetry for a job in order. Returns the count."""
    for sequence, event in enumerate(events):
        db.add(
            TelemetryEvent(
                job_id=job_id,
                sequence=sequence,
                category=TelemetryCategory(event.category),
                action=event.action,
                target=event.target[:1024],
                raw=event.raw,
            )
        )
    return len(events)


def list_events(
    db: Session, job_id: int, *, category: TelemetryCategory | None = None
) -> list[TelemetryEvent]:
    stmt = select(TelemetryEvent).where(TelemetryEvent.job_id == job_id)
    if category is not None:
        stmt = stmt.where(TelemetryEvent.category == category)
    return list(db.execute(stmt.order_by(TelemetryEvent.sequence)).scalars())
