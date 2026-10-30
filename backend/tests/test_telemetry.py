import io

import pytest
from fastapi.testclient import TestClient

from app.telemetry.normalizer import canonicalize, normalize
from tests.conftest import auth_header, run_queued


def test_canonicalize_strips_volatile_fields() -> None:
    assert canonicalize("file", "C:\\Users\\bob\\AppData\\sim_987.tmp") == (
        "C:\\Users\\<user>\\AppData\\sim_<n>.tmp"
    )
    assert canonicalize("mutex", "Global\\sim_12345") == "Global\\sim_<n>"
    assert canonicalize("dns", "XXXX.Example-C2.test") == "xxxx.example-c2.test"


def test_normalize_maps_observations_to_categories() -> None:
    observations = {
        "processes": [{"name": "sample.exe", "action": "start"}],
        "network": [
            {"type": "dns", "domain": "abcd.example-c2.test"},
            {"type": "tcp", "dest": "abcd.example-c2.test", "port": 443},
        ],
        "files_written": ["C:\\Users\\x\\sim_1.tmp"],
        "mutexes_created": ["Global\\sim_9"],
    }
    events = normalize(observations)
    categories = {e.category for e in events}
    assert categories == {"process", "dns", "network", "file", "mutex"}


@pytest.fixture()
def analyst_headers(client: TestClient, admin: dict[str, str]) -> dict[str, str]:
    headers = auth_header(client, admin["username"], admin["password"])
    client.post(
        "/api/v1/users",
        json={"username": "ana", "password": "analyst-pass-1", "role": "analyst"},
        headers=headers,
    )
    return auth_header(client, "ana", "analyst-pass-1")


def _run_job(client: TestClient, headers: dict[str, str], conditions: dict[str, object]) -> int:
    sample_id = client.post(
        "/api/v1/samples",
        files={"file": ("s.bin", io.BytesIO(b"MZ telemetry"), "application/octet-stream")},
        headers=headers,
    ).json()["sample"]["id"]
    job_id: int = client.post(
        "/api/v1/jobs",
        json={"sample_id": sample_id, "conditions": conditions},
        headers=headers,
    ).json()["id"]
    run_queued()
    return job_id


def test_running_a_job_produces_telemetry(
    client: TestClient, analyst_headers: dict[str, str]
) -> None:
    job_id = _run_job(client, analyst_headers, {"internet": True})
    response = client.get(f"/api/v1/jobs/{job_id}/telemetry", headers=analyst_headers)
    assert response.status_code == 200
    events = response.json()
    assert len(events) > 0
    assert any(e["category"] == "dns" for e in events)  # online run contacts a host


def test_telemetry_can_be_filtered_by_category(
    client: TestClient, analyst_headers: dict[str, str]
) -> None:
    job_id = _run_job(client, analyst_headers, {"internet": True})
    response = client.get(
        f"/api/v1/jobs/{job_id}/telemetry?category=process", headers=analyst_headers
    )
    assert response.status_code == 200
    assert all(e["category"] == "process" for e in response.json())


def test_offline_run_has_no_network_telemetry(
    client: TestClient, analyst_headers: dict[str, str]
) -> None:
    job_id = _run_job(client, analyst_headers, {"internet": False})
    events = client.get(f"/api/v1/jobs/{job_id}/telemetry", headers=analyst_headers).json()
    assert not any(e["category"] in ("dns", "network") for e in events)
