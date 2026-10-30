import io
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import worker
from app.config import ConfigurationError
from app.database import Base
from app.models import AnalysisJob, JobStatus, Sample
from app.services import emergency_service, job_service
from app.services.worker_service import (
    RECOVERY_MESSAGE,
    LeaseHeartbeat,
    claim_next,
    recover_expired_leases,
    renew_lease,
)
from tests.conftest import auth_header, run_queued


@pytest.fixture()
def sample_id(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(job_service.storage, "load", lambda sha: b"MZ")
    sample = Sample(
        sha256="9" * 64, filename="q.bin", size_bytes=2, detected_type="pe", stored_path="unused"
    )
    db_session.add(sample)
    db_session.commit()
    return sample.id


def _queue(db: Session, sample_id: int) -> int:
    job = job_service.create_job(
        db, sample_id=sample_id, executor_name="simulated", conditions={}, submitted_by=None
    )
    return job.id


def test_claim_returns_oldest_pending_job_and_records_lease(
    db_session: Session, sample_id: int
) -> None:
    first = _queue(db_session, sample_id)
    second = _queue(db_session, sample_id)

    claimed = claim_next(db_session, owner="w1", lease=timedelta(seconds=90))
    assert claimed == first
    job = db_session.get(AnalysisJob, first)
    assert job is not None
    assert job.status == JobStatus.running
    assert job.lease_owner == "w1"
    assert job.lease_expires_at is not None

    assert claim_next(db_session, owner="w2", lease=timedelta(seconds=90)) == second
    assert claim_next(db_session, owner="w3", lease=timedelta(seconds=90)) is None


def test_queued_jobs_complete_through_the_worker(
    client: TestClient, db_session: Session, sample_id: int
) -> None:
    job_id = _queue(db_session, sample_id)
    assert run_queued() == 1
    job = db_session.get(AnalysisJob, job_id)
    assert job is not None
    assert job.status == JobStatus.completed
    assert job.lease_owner == "test-worker"


def test_stop_blocks_claims_and_keeps_queued_work(db_session: Session, sample_id: int) -> None:
    job_id = _queue(db_session, sample_id)
    emergency_service.set_active(db_session, active=True, actor_id=1)
    db_session.commit()

    assert claim_next(db_session, owner="w1", lease=timedelta(seconds=90)) is None
    job = db_session.get(AnalysisJob, job_id)
    assert job is not None
    assert job.status == JobStatus.pending

    emergency_service.set_active(db_session, active=False, actor_id=1)
    db_session.commit()
    assert claim_next(db_session, owner="w1", lease=timedelta(seconds=90)) == job_id


def test_expired_lease_is_failed_as_unknown_and_never_completed(
    db_session: Session, sample_id: int
) -> None:
    job_id = _queue(db_session, sample_id)
    claim_next(db_session, owner="w1", lease=timedelta(seconds=90))
    later = datetime.now(UTC) + timedelta(hours=1)

    assert recover_expired_leases(db_session, now=later) == 1
    job = db_session.get(AnalysisJob, job_id)
    assert job is not None
    assert job.status == JobStatus.failed
    assert job.error == RECOVERY_MESSAGE
    assert job.result is None
    assert job.lease_owner is None


def test_live_lease_is_not_recovered(db_session: Session, sample_id: int) -> None:
    job_id = _queue(db_session, sample_id)
    claim_next(db_session, owner="w1", lease=timedelta(seconds=90))

    assert recover_expired_leases(db_session) == 0
    job = db_session.get(AnalysisJob, job_id)
    assert job is not None
    assert job.status == JobStatus.running


def test_worker_that_lost_its_lease_cannot_write_a_result(
    db_session: Session, sample_id: int
) -> None:
    job_id = _queue(db_session, sample_id)
    claim_next(db_session, owner="w1", lease=timedelta(seconds=90))
    recover_expired_leases(db_session, now=datetime.now(UTC) + timedelta(hours=1))

    job = db_session.get(AnalysisJob, job_id)
    assert job is not None
    job_service.run_job(db_session, job, owner="w1")
    db_session.refresh(job)
    assert job.status == JobStatus.failed
    assert job.result is None
    assert job.error == RECOVERY_MESSAGE


@pytest.fixture()
def people(client: TestClient, admin: dict[str, str]) -> dict[str, dict[str, str]]:
    admin_headers = auth_header(client, admin["username"], admin["password"])
    for username, role in (("q-analyst-a", "analyst"), ("q-analyst-b", "analyst")):
        client.post(
            "/api/v1/users",
            json={"username": username, "password": f"{username}-pass-1", "role": role},
            headers=admin_headers,
        )
    return {
        "admin": admin_headers,
        "a": auth_header(client, "q-analyst-a", "q-analyst-a-pass-1"),
        "b": auth_header(client, "q-analyst-b", "q-analyst-b-pass-1"),
    }


def _api_job(client: TestClient, headers: dict[str, str], sample_id: int) -> int:
    return client.post(
        "/api/v1/jobs",
        json={"sample_id": sample_id, "conditions": {}},
        headers=headers,
    ).json()["id"]


def test_submitter_cancels_queued_job_and_repeat_is_idempotent(
    client: TestClient, people: dict[str, dict[str, str]], db_session: Session, sample_id: int
) -> None:
    job_id = _api_job(client, people["a"], sample_id)
    first = client.post(f"/api/v1/jobs/{job_id}/cancel", headers=people["a"])
    assert first.status_code == 200
    assert first.json()["status"] == "cancelled"
    again = client.post(f"/api/v1/jobs/{job_id}/cancel", headers=people["a"])
    assert again.status_code == 200
    assert again.json()["status"] == "cancelled"
    assert run_queued() == 0  # a cancelled job is never claimed


def test_other_analyst_cannot_cancel_and_admin_can(
    client: TestClient, people: dict[str, dict[str, str]], db_session: Session, sample_id: int
) -> None:
    job_id = _api_job(client, people["a"], sample_id)
    denied = client.post(f"/api/v1/jobs/{job_id}/cancel", headers=people["b"])
    assert denied.status_code == 403
    allowed = client.post(f"/api/v1/jobs/{job_id}/cancel", headers=people["admin"])
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "cancelled"


def test_running_job_gets_a_stop_request(
    client: TestClient, people: dict[str, dict[str, str]], db_session: Session, sample_id: int
) -> None:
    job_id = _api_job(client, people["a"], sample_id)
    claim_next(db_session, owner="w1", lease=timedelta(seconds=90))
    response = client.post(f"/api/v1/jobs/{job_id}/cancel", headers=people["a"])
    assert response.status_code == 202  # stop requested; the job stays running until confirmed
    job = db_session.get(AnalysisJob, job_id)
    assert job is not None
    assert job.status == JobStatus.running
    assert job.cancel_requested is True


def test_cancel_unknown_job_is_404(client: TestClient, people: dict[str, dict[str, str]]) -> None:
    assert client.post("/api/v1/jobs/999999/cancel", headers=people["a"]).status_code == 404


def test_requested_timeout_is_validated_and_returned(
    client: TestClient, people: dict[str, dict[str, str]]
) -> None:
    sample_id = client.post(
        "/api/v1/samples",
        files={"file": ("t.bin", io.BytesIO(b"MZ timeout"), "application/octet-stream")},
        headers=people["a"],
    ).json()["sample"]["id"]

    accepted = client.post(
        "/api/v1/jobs",
        json={"sample_id": sample_id, "timeout_seconds": 7},
        headers=people["a"],
    )
    assert accepted.status_code == 201
    assert accepted.json()["timeout_seconds"] == 7
    for rejected in (0, 3601):
        response = client.post(
            "/api/v1/jobs",
            json={"sample_id": sample_id, "timeout_seconds": rejected},
            headers=people["a"],
        )
        assert response.status_code == 422


def test_worker_enforces_the_requested_timeout(
    client: TestClient, people: dict[str, dict[str, str]]
) -> None:
    sample_id = client.post(
        "/api/v1/samples",
        files={"file": ("h.bin", io.BytesIO(b"MZ hang"), "application/octet-stream")},
        headers=people["a"],
    ).json()["sample"]["id"]
    job_id = client.post(
        "/api/v1/jobs",
        json={"sample_id": sample_id, "executor": "hanging", "timeout_seconds": 1},
        headers=people["a"],
    ).json()["id"]

    started = time.monotonic()
    assert run_queued() == 1
    elapsed = time.monotonic() - started

    job = client.get(f"/api/v1/jobs/{job_id}", headers=people["a"]).json()
    assert job["status"] == "timed_out"
    assert job["error"] == "execution exceeded timeout"
    assert elapsed < 5, "the 1-second request limit, not the executor's wait, ended the run"


def test_renewal_extends_only_the_holders_live_lease(db_session: Session, sample_id: int) -> None:
    job_id = _queue(db_session, sample_id)
    assert claim_next(db_session, owner="w1", lease=timedelta(seconds=5)) == job_id

    assert renew_lease(db_session, job_id, owner="w2", lease=timedelta(seconds=90)) is False
    assert renew_lease(db_session, job_id, owner="w1", lease=timedelta(seconds=90)) is True

    later = datetime.now(UTC) + timedelta(seconds=30)
    assert recover_expired_leases(db_session, now=later) == 0  # extended beyond 5 seconds


def test_expired_lease_cannot_be_renewed_back_to_life(db_session: Session, sample_id: int) -> None:
    job_id = _queue(db_session, sample_id)
    assert claim_next(db_session, owner="w1", lease=timedelta(seconds=-1)) == job_id

    assert renew_lease(db_session, job_id, owner="w1", lease=timedelta(seconds=90)) is False
    assert recover_expired_leases(db_session) == 1
    assert db_session.get(AnalysisJob, job_id).status == JobStatus.failed


def test_expired_but_unrecovered_lease_cannot_complete_the_job(
    db_session: Session, sample_id: int
) -> None:
    job_id = _queue(db_session, sample_id)
    assert claim_next(db_session, owner="w1", lease=timedelta(seconds=-1)) == job_id
    job = db_session.get(AnalysisJob, job_id)

    job_service._settle(db_session, job, "w1", JobStatus.completed, error=None)

    assert job.status == JobStatus.running
    assert job.finished_at is None


def test_heartbeat_keeps_a_live_job_from_being_recovered(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'heartbeat.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    lease = timedelta(milliseconds=300)
    try:
        with factory() as db:
            sample = Sample(
                sha256="e" * 64,
                filename="hb.bin",
                size_bytes=2,
                detected_type="pe",
                stored_path="unused",
            )
            db.add(sample)
            db.commit()
            job_id = job_service.create_job(
                db, sample_id=sample.id, executor_name="simulated", conditions={}, submitted_by=None
            ).id
            assert claim_next(db, owner="w1", lease=lease) == job_id

        with LeaseHeartbeat(
            factory, job_id, owner="w1", lease=lease, interval=timedelta(milliseconds=50)
        ):
            time.sleep(0.8)  # several times the lease; only renewals keep it alive
            with factory() as db:
                assert recover_expired_leases(db) == 0

        with factory() as db:
            # The heartbeat has stopped, so the lease lapses and recovery takes over.
            assert recover_expired_leases(db, now=datetime.now(UTC) + timedelta(seconds=5)) == 1
            assert db.get(AnalysisJob, job_id).error == RECOVERY_MESSAGE
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "database_url",
    ["sqlite:///./cerberus.db", "sqlite://", "mysql+pymysql://user@localhost/cerberus"],
)
def test_worker_refuses_unsupported_databases(
    monkeypatch: pytest.MonkeyPatch, database_url: str
) -> None:
    monkeypatch.setattr(worker.settings, "database_url", database_url)
    with pytest.raises(ConfigurationError, match="requires PostgreSQL"):
        worker.main()  # raises before the polling loop starts


def test_worker_accepts_postgresql_urls() -> None:
    worker.require_postgresql("postgresql+psycopg://user@localhost:5432/cerberus")
