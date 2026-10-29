import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.executors import registry
from app.executors.base import ExecutionRequest, ExecutionResult
from app.models import AnalysisJob, JobStatus, Sample
from app.services import job_service
from tests.conftest import auth_header


@pytest.fixture()
def analyst_headers(client: TestClient, admin: dict[str, str]) -> dict[str, str]:
    headers = auth_header(client, admin["username"], admin["password"])
    client.post(
        "/api/v1/users",
        json={"username": "ana", "password": "analyst-pass-1", "role": "analyst"},
        headers=headers,
    )
    return auth_header(client, "ana", "analyst-pass-1")


def _upload_sample(client: TestClient, headers: dict[str, str]) -> int:
    response = client.post(
        "/api/v1/samples",
        files={"file": ("s.bin", io.BytesIO(b"MZ job sample"), "application/octet-stream")},
        headers=headers,
    )
    return response.json()["sample"]["id"]


def test_submit_job_runs_to_completion(
    client: TestClient, analyst_headers: dict[str, str]
) -> None:
    sample_id = _upload_sample(client, analyst_headers)
    response = client.post(
        "/api/v1/jobs",
        json={"sample_id": sample_id, "conditions": {"internet": True}},
        headers=analyst_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["result"]["network"]  # simulated network activity present
    assert body["duration_ms"] is not None


def test_job_for_unknown_sample_is_404(
    client: TestClient, analyst_headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/jobs", json={"sample_id": 9999}, headers=analyst_headers
    )
    assert response.status_code == 404


def test_unknown_executor_is_400(client: TestClient, analyst_headers: dict[str, str]) -> None:
    sample_id = _upload_sample(client, analyst_headers)
    response = client.post(
        "/api/v1/jobs",
        json={"sample_id": sample_id, "executor": "does-not-exist"},
        headers=analyst_headers,
    )
    assert response.status_code == 400


def test_viewer_cannot_submit_job(client: TestClient, admin: dict[str, str]) -> None:
    admin_headers = auth_header(client, admin["username"], admin["password"])
    analyst = auth_header(client, admin["username"], admin["password"])
    client.post(
        "/api/v1/users",
        json={"username": "ana2", "password": "analyst-pass-1", "role": "analyst"},
        headers=admin_headers,
    )
    sample_id = _upload_sample(client, auth_header(client, "ana2", "analyst-pass-1"))

    client.post(
        "/api/v1/users",
        json={"username": "vwr", "password": "viewer-pass-1", "role": "viewer"},
        headers=admin_headers,
    )
    viewer = auth_header(client, "vwr", "viewer-pass-1")
    assert (
        client.post("/api/v1/jobs", json={"sample_id": sample_id}, headers=viewer).status_code
        == 403
    )
    assert analyst  # silence unused


def test_timeout_marks_job_timed_out(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A slow executor that ignores the deadline; job_service must time it out.
    class SlowExecutor:
        name = "slow"

        def run(self, request: ExecutionRequest) -> ExecutionResult:
            import time

            time.sleep(5)
            return ExecutionResult(status="completed", duration_ms=0, observations={})

    monkeypatch.setitem(registry._EXECUTORS, "slow", SlowExecutor())

    sample = Sample(
        sha256="c" * 64,
        filename="s.bin",
        size_bytes=2,
        detected_type="pe",
        stored_path="unused",
    )
    db_session.add(sample)
    db_session.flush()
    job = AnalysisJob(sample_id=sample.id, executor="slow", conditions={})
    db_session.add(job)
    db_session.flush()

    # Storage isn't needed because the slow executor never reads it; patch load.
    monkeypatch.setattr(job_service.storage, "load", lambda sha: b"MZ")
    job_service.run_job(db_session, job, timeout_seconds=1)
    assert job.status == JobStatus.timed_out
    assert job.error == "execution exceeded timeout"
