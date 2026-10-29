from sqlalchemy.orm import Session

from app.config import settings
from app.models import AnalysisJob, JobStatus, Sample
from app.services import job_service


def test_missing_blob_marks_job_failed_with_sanitized_error(db_session: Session) -> None:
    # No blob is stored for this hash, so storage.load raises before execution.
    sample = Sample(
        sha256="f" * 64,
        filename="missing.bin",
        size_bytes=2,
        detected_type="pe",
        stored_path="unused",
    )
    db_session.add(sample)
    db_session.flush()
    job = AnalysisJob(sample_id=sample.id, executor="simulated", conditions={})
    db_session.add(job)
    db_session.flush()

    job_service.run_job(db_session, job, timeout_seconds=5)

    assert job.status == JobStatus.failed
    assert job.error == "sample data unavailable"
    assert job.finished_at is not None
    assert settings.sample_storage_dir not in job.error
    assert "/" not in job.error
