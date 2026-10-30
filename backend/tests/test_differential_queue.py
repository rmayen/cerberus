"""Queued differential analyses: cancellation, child-job rules, crash recovery, finalization."""

import threading
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.executors import registry
from app.executors.base import ExecutionRequest, ExecutionResult
from app.models import AnalysisJob, DifferentialAnalysis, DifferentialFinding, JobStatus, Sample
from app.services import differential_service, job_service
from app.services.worker_service import claim_next, process_next, recover_expired_leases
from tests.conftest import auth_header, run_queued


@pytest.fixture()
def people(client: TestClient, admin: dict[str, str]) -> dict[str, dict[str, str]]:
    admin_headers = auth_header(client, admin["username"], admin["password"])
    for username in ("dq-a", "dq-b"):
        client.post(
            "/api/v1/users",
            json={"username": username, "password": f"{username}-pass-1", "role": "analyst"},
            headers=admin_headers,
        )
    return {
        "admin": admin_headers,
        "a": auth_header(client, "dq-a", "dq-a-pass-1"),
        "b": auth_header(client, "dq-b", "dq-b-pass-1"),
    }


@pytest.fixture()
def sample(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(job_service.storage, "load", lambda sha: b"MZ")
    row = Sample(
        sha256="d" * 64, filename="dq.bin", size_bytes=2, detected_type="pe", stored_path="unused"
    )
    db_session.add(row)
    db_session.commit()
    return row.id


def _post(client: TestClient, headers: dict[str, str], sample_id: int, **extra: object) -> dict:
    body = {
        "sample_id": sample_id,
        "baseline_conditions": {"internet": True},
        "variations": [{"internet": False}],
        **extra,
    }
    response = client.post("/api/v1/differential", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _children(db: Session, analysis_id: int) -> list[AnalysisJob]:
    return differential_service.children(db, analysis_id)


def test_queued_analysis_is_pending_with_baseline_and_variant_jobs(
    client: TestClient, people: dict[str, dict[str, str]], sample: int, db_session: Session
) -> None:
    analysis = _post(client, people["a"], sample, timeout_seconds=7)
    assert analysis["status"] == "pending"
    jobs = _children(db_session, analysis["id"])
    assert [(j.differential_role, j.status) for j in jobs] == [
        ("baseline", JobStatus.pending),
        ("variant", JobStatus.pending),
    ]
    assert jobs[1].differential_variation == {"internet": False}
    assert {j.timeout_seconds for j in jobs} == {7}


def test_cancel_queued_analysis_is_atomic_and_idempotent(
    client: TestClient, people: dict[str, dict[str, str]], sample: int
) -> None:
    analysis_id = _post(client, people["a"], sample)["id"]

    first = client.post(f"/api/v1/differential/{analysis_id}/cancel", headers=people["a"])
    assert first.status_code == 200
    assert first.json()["status"] == "cancelled"
    again = client.post(f"/api/v1/differential/{analysis_id}/cancel", headers=people["a"])
    assert again.status_code == 200
    assert again.json()["status"] == "cancelled"

    assert run_queued() == 0  # cancelled children are never claimed
    jobs = client.get(f"/api/v1/jobs?sample_id={sample}", headers=people["a"]).json()
    assert [job["status"] for job in jobs] == ["cancelled", "cancelled"]
    assert all(job["differential_id"] == analysis_id for job in jobs)


def test_cancel_after_a_run_started_is_refused(
    client: TestClient, people: dict[str, dict[str, str]], sample: int, db_session: Session
) -> None:
    analysis_id = _post(client, people["a"], sample)["id"]
    assert process_next(db_session, owner="test-worker") is not None  # baseline completes

    response = client.post(f"/api/v1/differential/{analysis_id}/cancel", headers=people["a"])
    assert response.status_code == 409
    assert response.json()["detail"].startswith("analysis is ")


def test_child_job_cannot_be_cancelled_directly(
    client: TestClient, people: dict[str, dict[str, str]], sample: int
) -> None:
    analysis_id = _post(client, people["a"], sample)["id"]
    child_id = client.get(f"/api/v1/jobs?sample_id={sample}", headers=people["a"]).json()[0]["id"]

    response = client.post(f"/api/v1/jobs/{child_id}/cancel", headers=people["a"])
    assert response.status_code == 409
    assert f"differential analysis {analysis_id}" in response.json()["detail"]


def test_only_submitter_or_admin_can_cancel_an_analysis(
    client: TestClient, people: dict[str, dict[str, str]], sample: int
) -> None:
    analysis_id = _post(client, people["a"], sample)["id"]
    assert (
        client.post(f"/api/v1/differential/{analysis_id}/cancel", headers=people["b"]).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/differential/{analysis_id}/cancel", headers=people["admin"]
        ).status_code
        == 200
    )


def test_unknown_analysis_cancel_is_404(
    client: TestClient, people: dict[str, dict[str, str]]
) -> None:
    response = client.post("/api/v1/differential/999999/cancel", headers=people["a"])
    assert response.status_code == 404


def test_crashed_baseline_fails_analysis_and_is_never_rerun(
    client: TestClient, people: dict[str, dict[str, str]], sample: int, db_session: Session
) -> None:
    analysis_id = _post(client, people["a"], sample)["id"]
    # A worker claims the baseline, then dies: its lease is already expired.
    assert claim_next(db_session, owner="crashed", lease=timedelta(seconds=-1)) is not None
    assert recover_expired_leases(db_session) == 1

    run_queued()  # the variant runs; the baseline is never retried
    body = client.get(f"/api/v1/differential/{analysis_id}", headers=people["a"]).json()
    assert body["status"] == "failed"
    assert body["findings"] == []
    assert body["error_message"] == "Baseline run failed. The other runs were not compared."
    baseline = next(
        j for j in _children(db_session, analysis_id) if j.differential_role == "baseline"
    )
    assert baseline.status == JobStatus.failed
    assert baseline.result is None


def test_finalization_runs_once_and_only_after_children_are_terminal(
    client: TestClient, people: dict[str, dict[str, str]], sample: int, db_session: Session
) -> None:
    analysis_id = _post(client, people["a"], sample)["id"]
    assert process_next(db_session, owner="test-worker") is not None
    assert differential_service.finalize_ready(db_session) == 0  # variant still queued

    run_queued()
    assert differential_service.finalize_ready(db_session) == 0  # already finalized by run_queued
    analysis = db_session.get(DifferentialAnalysis, analysis_id)
    assert analysis.status == JobStatus.completed
    assert analysis.findings


def test_variant_is_claimable_only_after_its_baseline_completes(
    client: TestClient, people: dict[str, dict[str, str]], sample: int, db_session: Session
) -> None:
    analysis_id = _post(client, people["a"], sample)["id"]
    baseline_id, variant_id = [j.id for j in _children(db_session, analysis_id)]

    assert claim_next(db_session, owner="w1") == baseline_id
    assert claim_next(db_session, owner="w2") is None  # baseline running: variant not eligible

    baseline = db_session.get(AnalysisJob, baseline_id)
    job_service.run_job(db_session, baseline, owner="w1")  # completes and commits
    assert claim_next(db_session, owner="w2") == variant_id


class _RecordingExecutor:
    """Harmless test executor that hangs on every run and counts how many it started."""

    name = "recording"

    def __init__(self) -> None:
        self.calls = 0
        self.release = threading.Event()

    def run(self, request: ExecutionRequest) -> ExecutionResult:
        self.calls += 1
        self.release.wait(10)
        return ExecutionResult(status="completed", duration_ms=0, observations={})


def test_timed_out_baseline_fails_analysis_and_never_runs_variants(
    client: TestClient,
    people: dict[str, dict[str, str]],
    sample: int,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recording = _RecordingExecutor()
    monkeypatch.setitem(registry._EXECUTORS, recording.name, recording)
    analysis = differential_service.enqueue(
        db_session,
        sample_id=sample,
        baseline_conditions={},
        variations=[{"internet": False}, {"existing_mutex": True}],
        executor_name="recording",
        submitted_by=None,
        timeout_seconds=1,
    )
    try:
        run_queued()
    finally:
        recording.release.set()

    assert recording.calls == 1, "only the baseline may start"
    db_session.refresh(analysis)
    assert analysis.status == JobStatus.failed
    assert analysis.error_message == "Baseline run timed out. The other runs were not compared."
    jobs = _children(db_session, analysis.id)
    assert [j.status for j in jobs] == [
        JobStatus.timed_out,
        JobStatus.cancelled,
        JobStatus.cancelled,
    ]
    assert all(j.result is None for j in jobs[1:])
    assert db_session.query(DifferentialFinding).filter_by(analysis_id=analysis.id).count() == 0
