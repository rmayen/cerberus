from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AuditLog
from tests.conftest import auth_header, login


def test_login_success_returns_token_pair(client: TestClient, admin: dict[str, str]) -> None:
    tokens = login(client, admin["username"], admin["password"])
    assert tokens["access_token"]
    assert tokens["refresh_token"]
    assert tokens["token_type"] == "bearer"


def test_login_wrong_password_rejected(client: TestClient, admin: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "wrong"}
    )
    assert response.status_code == 401


def test_me_requires_auth(client: TestClient, admin: dict[str, str]) -> None:
    assert client.get("/api/v1/auth/me").status_code == 401

    headers = auth_header(client, admin["username"], admin["password"])
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["username"] == "admin"
    assert me.json()["role"] == "administrator"


def test_refresh_issues_new_access_token(client: TestClient, admin: dict[str, str]) -> None:
    tokens = login(client, admin["username"], admin["password"])
    response = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_logout_revokes_refresh_token(client: TestClient, admin: dict[str, str]) -> None:
    tokens = login(client, admin["username"], admin["password"])
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    logout = client.post(
        "/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}, headers=headers
    )
    assert logout.status_code == 204

    # The revoked refresh token can no longer be used.
    reused = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert reused.status_code == 401


def test_account_locks_after_repeated_failures(client: TestClient, admin: dict[str, str]) -> None:
    for _ in range(settings.login_max_failures):
        client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})

    # Even the correct password is now refused while locked.
    response = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": admin["password"]}
    )
    assert response.status_code == 401
    assert "locked" in response.json()["detail"]


def test_password_reset_flow(client: TestClient, admin: dict[str, str]) -> None:
    issued = client.post("/api/v1/auth/password-reset/request", json={"username": "admin"})
    assert issued.status_code == 200
    token = issued.json()["reset_token"]

    confirm = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": "brand-new-password"},
    )
    assert confirm.status_code == 204

    # Old password no longer works; new one does.
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": admin["password"]}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "brand-new-password"}
        ).status_code
        == 200
    )


def test_login_is_audited(client: TestClient, admin: dict[str, str], db_session: Session) -> None:
    login(client, admin["username"], admin["password"])
    actions = set(db_session.execute(select(AuditLog.action)).scalars())
    assert "login_success" in actions
