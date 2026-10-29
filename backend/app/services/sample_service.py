import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import filetype
from app.config import settings
from app.models import Case, Sample
from app.storage import storage


class SampleError(Exception):
    """Base class for sample intake failures."""


class EmptySample(SampleError):
    pass


class SampleTooLarge(SampleError):
    pass


class DisallowedFileType(SampleError):
    def __init__(self, detected: str) -> None:
        super().__init__(detected)
        self.detected = detected


class UnknownCase(SampleError):
    pass


def get_by_sha256(db: Session, sha256: str) -> Sample | None:
    return db.execute(select(Sample).where(Sample.sha256 == sha256)).scalar_one_or_none()


def get_by_id(db: Session, sample_id: int) -> Sample | None:
    return db.get(Sample, sample_id)


def list_samples(
    db: Session,
    *,
    case_id: int | None = None,
    detected_type: str | None = None,
    search: str | None = None,
) -> list[Sample]:
    stmt = select(Sample)
    if case_id is not None:
        stmt = stmt.where(Sample.case_id == case_id)
    if detected_type is not None:
        stmt = stmt.where(Sample.detected_type == detected_type)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(Sample.filename.ilike(like) | Sample.sha256.ilike(like))
    stmt = stmt.order_by(Sample.created_at.desc())
    return list(db.execute(stmt).scalars())


def intake(
    db: Session,
    *,
    filename: str,
    content_type: str | None,
    data: bytes,
    uploaded_by: int | None,
    case_id: int | None,
    tags: list[str] | None = None,
) -> tuple[Sample, bool]:
    """Validate, hash, deduplicate, encrypt-and-store, and record a sample.

    Returns (sample, duplicate). If the same bytes were already ingested, the
    existing record is returned and no new blob is written.
    """
    if not data:
        raise EmptySample()
    if len(data) > settings.max_upload_bytes:
        raise SampleTooLarge()

    detected = filetype.detect(data)
    if detected not in settings.allowed_types:
        raise DisallowedFileType(detected)

    if case_id is not None and db.get(Case, case_id) is None:
        raise UnknownCase()

    sha256 = hashlib.sha256(data).hexdigest()
    existing = get_by_sha256(db, sha256)
    if existing is not None:
        return existing, True

    stored_path = storage.store(sha256, data)
    sample = Sample(
        sha256=sha256,
        filename=filename[:255],
        size_bytes=len(data),
        content_type=(content_type or None),
        detected_type=detected,
        stored_path=stored_path,
        tags=_clean_tags(tags),
        case_id=case_id,
        uploaded_by=uploaded_by,
    )
    db.add(sample)
    db.flush()
    return sample, False


def set_tags(db: Session, sample: Sample, tags: list[str]) -> Sample:
    sample.tags = _clean_tags(tags)
    db.flush()
    return sample


def _clean_tags(tags: list[str] | None) -> list[str]:
    if not tags:
        return []
    seen: list[str] = []
    for tag in tags:
        cleaned = tag.strip()[:50]
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return seen
