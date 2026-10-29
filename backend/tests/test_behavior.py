import io
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from app.analysis.behavior import analyze
from tests.conftest import auth_header


@dataclass
class Ev:
    category: str
    action: str
    target: str


def test_network_and_persistence_are_detected() -> None:
    events = [
        Ev("dns", "query", "abcd.example-c2.test"),
        Ev("registry", "set", "hkcu\\...\\currentversion\\run\\sim_<n>"),
    ]
    findings = {f.category: f for f in analyze(events)}
    assert "network" in findings
    assert findings["network"].severity == "medium"
    assert "persistence" in findings
    assert findings["persistence"].severity == "high"


def test_privilege_escalation_marker_detected() -> None:
    findings = analyze([Ev("process", "getsystem", "sample.exe")])
    assert any(f.category == "privilege_escalation" for f in findings)


def test_no_events_yields_no_findings() -> None:
    assert analyze([]) == []


@pytest.fixture()
def analyst_headers(client: TestClient, admin: dict[str, str]) -> dict[str, str]:
    headers = auth_header(client, admin["username"], admin["password"])
    client.post(
        "/api/v1/users",
        json={"username": "ana", "password": "analyst-pass-1", "role": "analyst"},
        headers=headers,
    )
    return auth_header(client, "ana", "analyst-pass-1")


def test_completed_job_has_explainable_findings(
    client: TestClient, analyst_headers: dict[str, str]
) -> None:
    sample_id = client.post(
        "/api/v1/samples",
        files={"file": ("s.bin", io.BytesIO(b"MZ behavior"), "application/octet-stream")},
        headers=analyst_headers,
    ).json()["sample"]["id"]
    job_id = client.post(
        "/api/v1/jobs",
        json={"sample_id": sample_id, "conditions": {"internet": True}},
        headers=analyst_headers,
    ).json()["id"]

    response = client.get(f"/api/v1/jobs/{job_id}/findings", headers=analyst_headers)
    assert response.status_code == 200
    findings = response.json()
    categories = {f["category"] for f in findings}
    # A nominal online run should surface network, persistence, and more.
    assert {"network", "persistence"} <= categories
    for finding in findings:
        assert finding["explanation"]  # every finding is explainable
        assert finding["evidence"]
