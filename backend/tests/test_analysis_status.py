import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import AnalysisJob, JobStatus, Sample, SampleStatus
from app.services.job_service import ANALYSIS_STATE, analysis_states
from tests.conftest import auth_header


def _sample(db: Session, n: int) -> Sample:
    sample = Sample(
        sha256=f"{n:064x}",
        filename=f"sample-{n}.txt",
        size_bytes=1,
        stored_path="unused",
        status=SampleStatus.quarantined,
    )
    db.add(sample)
    db.flush()
    return sample


def _job(db: Session, sample: Sample, status: JobStatus) -> AnalysisJob:
    job = AnalysisJob(sample_id=sample.id, executor="simulated", conditions={}, status=status)
    db.add(job)
    db.flush()
    return job


@pytest.mark.parametrize(
    ("job_status", "expected"),
    [
        (JobStatus.pending, "analyzing"),
        (JobStatus.running, "analyzing"),
        (JobStatus.completed, "analyzed"),
        (JobStatus.failed, "failed"),
        (JobStatus.timed_out, "failed"),
        (JobStatus.cancelled, "not_analyzed"),
    ],
)
def test_job_status_maps_to_analysis_state(job_status: JobStatus, expected: str) -> None:
    assert ANALYSIS_STATE[job_status] == expected


def test_every_job_status_has_a_mapping() -> None:
    assert set(ANALYSIS_STATE) == set(JobStatus)


def test_sample_without_jobs_has_no_state(db_session: Session) -> None:
    sample = _sample(db_session, 1)
    assert analysis_states(db_session, [sample.id]) == {}


def test_latest_job_decides_the_state(db_session: Session) -> None:
    sample = _sample(db_session, 2)
    _job(db_session, sample, JobStatus.completed)
    _job(db_session, sample, JobStatus.failed)
    assert analysis_states(db_session, [sample.id]) == {sample.id: "failed"}

    _job(db_session, sample, JobStatus.pending)
    assert analysis_states(db_session, [sample.id]) == {sample.id: "analyzing"}


def test_listing_reports_each_state_and_keeps_storage_status(
    client: TestClient, db_session: Session, admin: dict[str, str]
) -> None:
    fresh = _sample(db_session, 3)
    done = _sample(db_session, 4)
    timed_out = _sample(db_session, 5)
    _job(db_session, done, JobStatus.completed)
    _job(db_session, timed_out, JobStatus.timed_out)
    db_session.commit()

    headers = auth_header(client, admin["username"], admin["password"])
    response = client.get("/api/v1/samples", headers=headers)
    assert response.status_code == 200
    by_sha = {item["sha256"]: item for item in response.json()}

    assert by_sha[fresh.sha256]["analysis_status"] == "not_analyzed"
    assert by_sha[done.sha256]["analysis_status"] == "analyzed"
    assert by_sha[timed_out.sha256]["analysis_status"] == "failed"
    # Analysis never changes the quarantine/storage status.
    assert {item["status"] for item in by_sha.values()} == {"quarantined"}
