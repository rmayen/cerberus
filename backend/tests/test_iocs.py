import io
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.analysis.ioc import extract
from tests.conftest import auth_header


@dataclass
class Ev:
    category: str
    raw: dict[str, Any] = field(default_factory=dict)


def test_extract_pulls_typed_indicators() -> None:
    events = [
        Ev("dns", {"domain": "evil.example-c2.test"}),
        Ev("network", {"dest": "203.0.113.10", "port": 443}),
        Ev("file", {"path": "C:\\Users\\x\\bad.exe"}),
        Ev("mutex", {"name": "Global\\lock"}),
    ]
    iocs = dict(extract("a" * 64, events))
    assert iocs["file_hash"] == "a" * 64
    pairs = set(extract("a" * 64, events))
    assert ("domain", "evil.example-c2.test") in pairs
    assert ("ip", "203.0.113.10") in pairs
    assert ("file_path", "C:\\Users\\x\\bad.exe") in pairs
    assert ("mutex", "Global\\lock") in pairs


@pytest.fixture()
def analyst_headers(client: TestClient, admin: dict[str, str]) -> dict[str, str]:
    headers = auth_header(client, admin["username"], admin["password"])
    client.post(
        "/api/v1/users",
        json={"username": "ana", "password": "analyst-pass-1", "role": "analyst"},
        headers=headers,
    )
    return auth_header(client, "ana", "analyst-pass-1")


def _upload_and_run(client: TestClient, headers: dict[str, str]) -> int:
    sample_id = client.post(
        "/api/v1/samples",
        files={"file": ("s.bin", io.BytesIO(b"MZ ioc sample"), "application/octet-stream")},
        headers=headers,
    ).json()["sample"]["id"]
    client.post(
        "/api/v1/jobs",
        json={"sample_id": sample_id, "conditions": {"internet": True}},
        headers=headers,
    )
    return sample_id


def test_running_a_job_extracts_iocs(
    client: TestClient, analyst_headers: dict[str, str]
) -> None:
    sample_id = _upload_and_run(client, analyst_headers)
    response = client.get(f"/api/v1/samples/{sample_id}/iocs", headers=analyst_headers)
    assert response.status_code == 200
    types = {i["type"] for i in response.json()}
    assert "file_hash" in types
    assert "domain" in types  # from the simulated online run


def test_iocs_can_be_exported_as_csv_and_json(
    client: TestClient, analyst_headers: dict[str, str]
) -> None:
    sample_id = _upload_and_run(client, analyst_headers)

    csv_resp = client.get(
        f"/api/v1/samples/{sample_id}/iocs/export?format=csv", headers=analyst_headers
    )
    assert csv_resp.status_code == 200
    assert csv_resp.headers["content-type"].startswith("text/csv")
    assert "type,value,first_seen" in csv_resp.text

    json_resp = client.get(
        f"/api/v1/samples/{sample_id}/iocs/export?format=json", headers=analyst_headers
    )
    assert json_resp.status_code == 200
    assert any(i["type"] == "file_hash" for i in json_resp.json())


def test_iocs_are_deduplicated_across_runs(
    client: TestClient, analyst_headers: dict[str, str]
) -> None:
    sample_id = _upload_and_run(client, analyst_headers)
    before = len(client.get(f"/api/v1/samples/{sample_id}/iocs", headers=analyst_headers).json())
    # Re-run the same sample; identical IOCs must not duplicate.
    client.post(
        "/api/v1/jobs",
        json={"sample_id": sample_id, "conditions": {"internet": True}},
        headers=analyst_headers,
    )
    after = len(client.get(f"/api/v1/samples/{sample_id}/iocs", headers=analyst_headers).json())
    assert before == after
