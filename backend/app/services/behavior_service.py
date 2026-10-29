from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.behavior import Finding
from app.models import BehaviorFinding, Severity


def store(db: Session, job_id: int, findings: list[Finding]) -> int:
    for finding in findings:
        db.add(
            BehaviorFinding(
                job_id=job_id,
                category=finding.category,
                title=finding.title,
                severity=Severity(finding.severity),
                explanation=finding.explanation,
                evidence=finding.evidence,
            )
        )
    return len(findings)


def list_findings(db: Session, job_id: int) -> list[BehaviorFinding]:
    stmt = (
        select(BehaviorFinding)
        .where(BehaviorFinding.job_id == job_id)
        .order_by(BehaviorFinding.id)
    )
    return list(db.execute(stmt).scalars())
