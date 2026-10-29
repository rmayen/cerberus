import io

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth_header


@pytest.fixture()
def roles(client: TestClient, admin: dict[str, str]) -> dict[str, dict[str, str]]:
    admin_headers = auth_header(client, admin["username"], admin["password"])
    for username, role in (("stop-analyst", "analyst"), ("stop-viewer", "viewer")):
        client.post(
            "/api/v1/users",
            json={"username": username, "password": f"{username}-pass-1", "role": role},
            headers=admin_headers,
        )
    return {
        "admin": admin_headers,
        "analyst": auth_header(client, "stop-analyst", "stop-analyst-pass-1"),
        "viewer": auth_header(client, "stop-viewer", "stop-viewer-pass-1"),
    }


def _sample(client: TestClient, headers: dict[str, str], content: bytes) -> int:
    response = client.post(
        "/api/v1/samples",
        files={"file": ("s.bin", io.BytesIO(content), "application/octet-stream")},
        headers=headers,
    )
    return response.json()["sample"]["id"]


def _set_stop(client: TestClient, headers: dict[str, str], active: bool) -> None:
    response = client.put("/api/v1/emergency-stop", json={"active": active}, headers=headers)
    assert response.status_code == 200, response.text


def test_stop_is_off_by_default_and_readable_by_viewers(
    client: TestClient, roles: dict[str, dict[str, str]]
) -> None:
    response = client.get("/api/v1/emergency-stop", headers=roles["viewer"])
    assert response.status_code == 200
    assert response.json() == {"active": False}


def test_stop_requires_authentication_to_read(client: TestClient) -> None:
    assert client.get("/api/v1/emergency-stop").status_code == 401


def test_only_administrators_can_change_stop(
    client: TestClient, roles: dict[str, dict[str, str]]
) -> None:
    for role in ("analyst", "viewer"):
        response = client.put(
            "/api/v1/emergency-stop", json={"active": True}, headers=roles[role]
        )
        assert response.status_code == 403
    assert client.get("/api/v1/emergency-stop", headers=roles["viewer"]).json() == {"active": False}


def test_active_stop_blocks_new_jobs_without_creating_records(
    client: TestClient, roles: dict[str, dict[str, str]]
) -> None:
    sample_id = _sample(client, roles["analyst"], b"MZ stop-job")
    _set_stop(client, roles["admin"], True)

    response = client.post(
        "/api/v1/jobs",
        json={"sample_id": sample_id, "executor": "simulated", "conditions": {}},
        headers=roles["analyst"],
    )
    assert response.status_code == 503
    assert "emergency stop" in response.json()["detail"]
    assert client.get("/api/v1/jobs", headers=roles["viewer"]).json() == []


def test_active_stop_blocks_new_differential_runs(
    client: TestClient, roles: dict[str, dict[str, str]]
) -> None:
    sample_id = _sample(client, roles["analyst"], b"MZ stop-diff")
    _set_stop(client, roles["admin"], True)

    response = client.post(
        "/api/v1/differential",
        json={
            "sample_id": sample_id,
            "baseline_conditions": {"internet": True},
            "variations": [{"internet": False}],
        },
        headers=roles["analyst"],
    )
    assert response.status_code == 503
    assert client.get("/api/v1/differential", headers=roles["viewer"]).json() == []


def test_clearing_stop_allows_jobs_again(
    client: TestClient, roles: dict[str, dict[str, str]]
) -> None:
    sample_id = _sample(client, roles["analyst"], b"MZ stop-resume")
    _set_stop(client, roles["admin"], True)
    _set_stop(client, roles["admin"], False)

    response = client.post(
        "/api/v1/jobs",
        json={"sample_id": sample_id, "executor": "simulated", "conditions": {}},
        headers=roles["analyst"],
    )
    assert response.status_code == 201
    assert response.json()["status"] == "completed"


def test_stop_does_not_alter_existing_job_records(
    client: TestClient, roles: dict[str, dict[str, str]]
) -> None:
    sample_id = _sample(client, roles["analyst"], b"MZ stop-existing")
    created = client.post(
        "/api/v1/jobs",
        json={"sample_id": sample_id, "executor": "simulated", "conditions": {}},
        headers=roles["analyst"],
    ).json()

    _set_stop(client, roles["admin"], True)
    fetched = client.get(f"/api/v1/jobs/{created['id']}", headers=roles["viewer"]).json()
    assert fetched["status"] == created["status"] == "completed"
