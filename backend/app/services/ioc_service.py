import csv
import io
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.ioc import _Event as IocEvent
from app.analysis.ioc import extract
from app.models import Ioc, IocType


def extract_and_store(
    db: Session,
    *,
    sample_id: int,
    job_id: int,
    sample_sha256: str,
    events: Sequence[IocEvent],
) -> int:
    """Extract IOCs from a run and store any not already known for the sample."""
    existing = {(i.type.value, i.value) for i in list_iocs(db, sample_id)}
    added = 0
    for type_name, value in extract(sample_sha256, events):
        if (type_name, value) in existing:
            continue
        db.add(
            Ioc(
                sample_id=sample_id,
                type=IocType(type_name),
                value=value[:1024],
                source_job_id=job_id,
            )
        )
        existing.add((type_name, value))
        added += 1
    return added


def list_iocs(db: Session, sample_id: int, *, type: IocType | None = None) -> list[Ioc]:
    stmt = select(Ioc).where(Ioc.sample_id == sample_id)
    if type is not None:
        stmt = stmt.where(Ioc.type == type)
    return list(db.execute(stmt.order_by(Ioc.type, Ioc.value)).scalars())


def to_csv(iocs: Sequence[Ioc]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["type", "value", "first_seen"])
    for ioc in iocs:
        writer.writerow([ioc.type.value, ioc.value, ioc.first_seen.isoformat()])
    return buffer.getvalue()


def to_json(iocs: Sequence[Ioc]) -> list[dict[str, str]]:
    return [
        {"type": ioc.type.value, "value": ioc.value, "first_seen": ioc.first_seen.isoformat()}
        for ioc in iocs
    ]
