import io
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

from app.analysis.attack import map_findings
from tests.conftest import auth_header


@dataclass
class F:
    category: str
    title: str
    evidence: list = field(default_factory=list)


def test_map_findings_produces_techniques() -> None:
    findings = [
        F("network", "Outbound network communication"),
        F("persistence", "Persistence mechanism"),
    ]
    mappings = {m.technique_id: m for m in map_findings(findings)}
    assert "T1071" in mappings
    assert mappings["T1071"].tactic == "Command and Control"
    assert "T1547.001" in mappings
    assert mappings["T1547.001"].explanation  # every mapping is explained


def test_map_findings_deduplicates_techniques() -> None:
    findings = [F("network", "a"), F("network", "b")]
    assert len(map_findings(findings)) == 1


@pytest.fixture()
def analyst_headers(client: TestClient, admin: dict[str, str]) -> dict[str, str]:
    headers = auth_header(client, admin["username"], admin["password"])
    client.post(
        "/api/v1/users",
        json={"username": "ana", "password": "analyst-pass-1", "role": "analyst"},
        headers=headers,
    )
    return auth_header(client, "ana", "analyst-pass-1")


def test_completed_job_has_attack_mappings(
    client: TestClient, analyst_headers: dict[str, str]
) -> None:
    sample_id = client.post(
        "/api/v1/samples",
        files={"file": ("s.bin", io.BytesIO(b"MZ attack"), "application/octet-stream")},
        headers=analyst_headers,
    ).json()["sample"]["id"]
    job_id = client.post(
        "/api/v1/jobs",
        json={"sample_id": sample_id, "conditions": {"internet": True}},
        headers=analyst_headers,
    ).json()["id"]

    response = client.get(f"/api/v1/jobs/{job_id}/attack", headers=analyst_headers)
    assert response.status_code == 200
    techniques = {m["technique_id"] for m in response.json()}
    assert {"T1071", "T1547.001"} <= techniques  # network + persistence from a nominal run
    for mapping in response.json():
        assert mapping["explanation"]
        assert mapping["tactic"]
