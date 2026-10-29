from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import require_role
from app.models import IocType, Role, Sample, User
from app.schemas import IocRead, SampleRead, SampleUploadResult, TagsUpdate
from app.services import audit, ioc_service, job_service, sample_service
from app.services.sample_service import (
    DisallowedFileType,
    EmptySample,
    SampleTooLarge,
    UnknownCase,
)

router = APIRouter(prefix="/api/v1/samples", tags=["samples"])


async def _read_limited(upload: UploadFile, limit: int) -> bytes:
    """Read an upload while enforcing the size limit, without buffering more than limit+1."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "sample exceeds the maximum upload size"
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("", response_model=SampleUploadResult, status_code=status.HTTP_201_CREATED)
async def upload_sample(
    request: Request,
    file: UploadFile = File(...),
    case_id: int | None = Form(default=None),
    tags: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.analyst, Role.administrator)),
) -> SampleUploadResult:
    data = await _read_limited(file, settings.max_upload_bytes)
    tag_list = [t for t in (tags or "").split(",") if t.strip()]
    try:
        sample, duplicate = sample_service.intake(
            db,
            filename=file.filename or "unnamed",
            content_type=file.content_type,
            data=data,
            uploaded_by=user.id,
            case_id=case_id,
            tags=tag_list,
        )
    except EmptySample as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty sample") from exc
    except SampleTooLarge as exc:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "sample too large") from exc
    except DisallowedFileType as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"file type not allowed: {exc.detected}"
        ) from exc
    except UnknownCase as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "case not found") from exc

    if not duplicate:
        audit.record(
            db,
            "sample_uploaded",
            actor_user_id=user.id,
            detail=f"{sample.sha256} ({sample.detected_type})",
            ip=request.client.host if request.client else None,
        )
    db.commit()
    return SampleUploadResult(sample=_sample_reads(db, [sample])[0], duplicate=duplicate)


def _sample_reads(db: Session, samples: list[Sample]) -> list[SampleRead]:
    """Serialize samples with their analysis state, using one query for the whole batch."""
    states = job_service.analysis_states(db, [s.id for s in samples])
    return [
        SampleRead.model_validate(s).model_copy(
            update={"analysis_status": states.get(s.id, "not_analyzed")}
        )
        for s in samples
    ]


@router.get("", response_model=list[SampleRead])
def list_samples(
    case_id: int | None = None,
    detected_type: str | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.viewer, Role.analyst, Role.administrator)),
) -> object:
    samples = sample_service.list_samples(
        db, case_id=case_id, detected_type=detected_type, search=search
    )
    return _sample_reads(db, list(samples))


@router.get("/{sample_id}", response_model=SampleRead)
def get_sample(
    sample_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.viewer, Role.analyst, Role.administrator)),
) -> object:
    sample = sample_service.get_by_id(db, sample_id)
    if sample is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "sample not found")
    return _sample_reads(db, [sample])[0]


@router.put("/{sample_id}/tags", response_model=SampleRead)
def update_tags(
    sample_id: int,
    body: TagsUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.analyst, Role.administrator)),
) -> object:
    sample = sample_service.get_by_id(db, sample_id)
    if sample is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "sample not found")
    sample = sample_service.set_tags(db, sample, body.tags)
    db.commit()
    return _sample_reads(db, [sample])[0]


@router.get("/{sample_id}/iocs", response_model=list[IocRead])
def list_iocs(
    sample_id: int,
    type: IocType | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.viewer, Role.analyst, Role.administrator)),
) -> object:
    if sample_service.get_by_id(db, sample_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "sample not found")
    return ioc_service.list_iocs(db, sample_id, type=type)


@router.get("/{sample_id}/iocs/export")
def export_iocs(
    sample_id: int,
    format: str = "json",
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.viewer, Role.analyst, Role.administrator)),
) -> Response:
    if sample_service.get_by_id(db, sample_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "sample not found")
    iocs = ioc_service.list_iocs(db, sample_id)

    if format == "csv":
        return Response(
            content=ioc_service.to_csv(iocs),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="iocs_{sample_id}.csv"'},
        )
    if format == "json":
        import json

        return Response(
            content=json.dumps(ioc_service.to_json(iocs), indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="iocs_{sample_id}.json"'},
        )
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "format must be json or csv")
