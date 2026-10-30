import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AnalysisJob, DifferentialAnalysis, DifferentialFinding, JobStatus, Sample
from app.services import differential_service, job_service
from app.services.worker_service import drain
from tests.conftest import auth_header, run_queued


@pytest.fixture()
def analyst_headers(client: TestClient, admin: dict[str, str]) -> dict[str, str]:
    headers = auth_header(client, admin["username"], admin["password"])
    client.post(
        "/api/v1/users",
        json={"username": "ana", "password": "analyst-pass-1", "role": "analyst"},
        headers=headers,
    )
    return auth_header(client, "ana", "analyst-pass-1")


@pytest.fixture()
def scripted(monkeypatch: pytest.MonkeyPatch) -> None:
    """The "scripted" executor lives in tests/executor_fixtures.py and runs in the child process."""
    monkeypatch.setattr(job_service.storage, "load", lambda sha: b"MZ")


def _sample(db: Session, sha: str) -> int:
    sample = Sample(
        sha256=sha,
        filename="s.bin",
        size_bytes=2,
        detected_type="pe",
        stored_path="unused",
    )
    db.add(sample)
    db.flush()
    return sample.id


def _findings(db: Session, analysis_id: int) -> list[DifferentialFinding]:
    return list(
        db.execute(
            select(DifferentialFinding).where(DifferentialFinding.analysis_id == analysis_id)
        ).scalars()
    )


def _run(
    db: Session,
    sample_id: int,
    baseline: dict[str, object],
    variations: list[dict[str, object]],
    timeout_seconds: int = 5,
) -> DifferentialAnalysis:
    analysis = differential_service.enqueue(
        db,
        sample_id=sample_id,
        baseline_conditions=baseline,
        variations=variations,
        executor_name="scripted",
        submitted_by=None,
        timeout_seconds=timeout_seconds,
    )
    drain(db, owner="test-worker")
    differential_service.finalize_ready(db)
    db.refresh(analysis)
    return analysis


def _jobs(db: Session, analysis_id: int) -> list[AnalysisJob]:
    return list(
        db.execute(
            select(AnalysisJob)
            .where(AnalysisJob.differential_id == analysis_id)
            .order_by(AnalysisJob.id)
        ).scalars()
    )


def test_failed_baseline_fails_analysis_without_findings(
    db_session: Session, scripted: None
) -> None:
    analysis = _run(
        db_session, _sample(db_session, "a" * 64), {"mode": "fail"}, [{"internet": False}]
    )

    assert analysis.status == JobStatus.failed
    assert analysis.finished_at is not None
    assert _findings(db_session, analysis.id) == []
    # Variants become claimable only after a completed baseline, so this one is cancelled unrun.
    assert [job.status for job in _jobs(db_session, analysis.id)] == [
        JobStatus.failed,
        JobStatus.cancelled,
    ]


def test_failed_variant_fails_analysis_and_keeps_job_records(
    db_session: Session, scripted: None
) -> None:
    analysis = _run(
        db_session,
        _sample(db_session, "b" * 64),
        {"internet": True},
        [{"internet": False}, {"mode": "fail"}],
    )

    assert analysis.status == JobStatus.failed
    assert _findings(db_session, analysis.id) == []
    statuses = [job.status for job in _jobs(db_session, analysis.id)]
    assert statuses == [JobStatus.completed, JobStatus.completed, JobStatus.failed]


def test_timed_out_variant_fails_analysis(db_session: Session, scripted: None) -> None:
    analysis = _run(
        db_session,
        _sample(db_session, "c" * 64),
        {"internet": True},
        [{"mode": "hang"}],
        timeout_seconds=1,
    )

    assert analysis.status == JobStatus.failed
    assert _findings(db_session, analysis.id) == []
    assert _jobs(db_session, analysis.id)[-1].status == JobStatus.timed_out


def test_successful_comparison_completes_with_findings(db_session: Session, scripted: None) -> None:
    analysis = _run(
        db_session, _sample(db_session, "d" * 64), {"internet": True}, [{"internet": False}]
    )

    assert analysis.status == JobStatus.completed
    assert analysis.finished_at is not None
    assert len(_findings(db_session, analysis.id)) > 0


def test_failed_differential_is_persisted_through_api(
    client: TestClient, analyst_headers: dict[str, str], scripted: None
) -> None:
    sample_id = client.post(
        "/api/v1/samples",
        files={"file": ("s.bin", io.BytesIO(b"MZ fail"), "application/octet-stream")},
        headers=analyst_headers,
    ).json()["sample"]["id"]

    response = client.post(
        "/api/v1/differential",
        json={
            "sample_id": sample_id,
            "executor": "scripted",
            "baseline_conditions": {"mode": "fail"},
            "variations": [{"internet": False}],
        },
        headers=analyst_headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "pending"  # queued; nothing ran in the request
    run_queued()
    analysis_id = response.json()["id"]
    body = client.get(f"/api/v1/differential/{analysis_id}", headers=analyst_headers).json()
    assert body["status"] == "failed"
    assert body["findings"] == []
    assert body["error_message"] == "Baseline run failed. The other runs were not compared."

    stored = client.get(f"/api/v1/differential/{body['id']}", headers=analyst_headers)
    assert stored.status_code == 200
    assert stored.json()["status"] == "failed"
    assert stored.json()["error_message"] == (
        "Baseline run failed. The other runs were not compared."
    )


def test_failure_message_is_fixed_and_hides_job_error(db_session: Session, scripted: None) -> None:
    analysis = _run(
        db_session, _sample(db_session, "g" * 64), {"mode": "fail"}, [{"internet": False}]
    )

    assert analysis.error_message == "Baseline run failed. The other runs were not compared."
    assert "scripted failure" not in analysis.error_message
    assert "/" not in analysis.error_message


def test_timeout_message_names_the_run(db_session: Session, scripted: None) -> None:
    analysis = _run(
        db_session,
        _sample(db_session, "h" * 64),
        {"internet": True},
        [{"mode": "hang"}],
        timeout_seconds=1,
    )

    assert analysis.error_message == "Variant run timed out. The other runs were not compared."


def test_successful_analysis_has_no_error_message(db_session: Session, scripted: None) -> None:
    analysis = _run(
        db_session, _sample(db_session, "i" * 64), {"internet": True}, [{"internet": False}]
    )

    assert analysis.error_message is None
