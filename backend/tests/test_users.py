from fastapi.testclient import TestClient

from tests.conftest import auth_header


def test_admin_can_create_user(client: TestClient, admin: dict[str, str]) -> None:
    headers = auth_header(client, admin["username"], admin["password"])
    response = client.post(
        "/api/v1/users",
        json={"username": "analyst1", "password": "analyst-pass-1", "role": "analyst"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["username"] == "analyst1"
    assert response.json()["role"] == "analyst"


def test_duplicate_username_conflicts(client: TestClient, admin: dict[str, str]) -> None:
    headers = auth_header(client, admin["username"], admin["password"])
    payload = {"username": "dupe", "password": "some-password-1", "role": "viewer"}
    assert client.post("/api/v1/users", json=payload, headers=headers).status_code == 201
    assert client.post("/api/v1/users", json=payload, headers=headers).status_code == 409


def test_viewer_cannot_create_user(client: TestClient, admin: dict[str, str]) -> None:
    headers = auth_header(client, admin["username"], admin["password"])
    client.post(
        "/api/v1/users",
        json={"username": "viewer1", "password": "viewer-pass-1", "role": "viewer"},
        headers=headers,
    )

    viewer_headers = auth_header(client, "viewer1", "viewer-pass-1")
    response = client.post(
        "/api/v1/users",
        json={"username": "nope", "password": "nope-pass-1", "role": "viewer"},
        headers=viewer_headers,
    )
    assert response.status_code == 403


def test_unauthenticated_cannot_list_users(client: TestClient) -> None:
    assert client.get("/api/v1/users").status_code == 401
