from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Case


class CaseAlreadyExists(Exception):
    pass


def get_by_name(db: Session, name: str) -> Case | None:
    return db.execute(select(Case).where(Case.name == name)).scalar_one_or_none()


def get_by_id(db: Session, case_id: int) -> Case | None:
    return db.get(Case, case_id)


def list_cases(db: Session) -> list[Case]:
    return list(db.execute(select(Case).order_by(Case.created_at.desc())).scalars())


def create_case(db: Session, name: str, description: str | None, created_by: int | None) -> Case:
    if get_by_name(db, name) is not None:
        raise CaseAlreadyExists(name)
    case = Case(name=name, description=description, created_by=created_by)
    db.add(case)
    db.flush()
    return case
