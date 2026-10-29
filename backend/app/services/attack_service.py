from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.attack import AttackMappingResult
from app.models import AttackMapping


def store(db: Session, job_id: int, mappings: Sequence[AttackMappingResult]) -> int:
    for mapping in mappings:
        db.add(
            AttackMapping(
                job_id=job_id,
                technique_id=mapping.technique_id,
                technique_name=mapping.technique_name,
                tactic=mapping.tactic,
                explanation=mapping.explanation,
                evidence=mapping.evidence,
            )
        )
    return len(mappings)


def list_mappings(db: Session, job_id: int) -> list[AttackMapping]:
    stmt = (
        select(AttackMapping)
        .where(AttackMapping.job_id == job_id)
        .order_by(AttackMapping.technique_id)
    )
    return list(db.execute(stmt).scalars())
