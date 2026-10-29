import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# The app refuses to start without a strong JWT secret and a Fernet storage key. Tests use these
# explicit test-only values, set before the app is imported. Values already in the environment win.
os.environ.setdefault("CERBERUS_JWT_SECRET", "test-only-jwt-secret-not-for-deployment-0123456789")
os.environ.setdefault("CERBERUS_STORAGE_KEY", "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=")

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models import Role
from app.services import job_service, sample_service, user_service
from app.storage import SampleStorage


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect encrypted sample storage to a per-test temp directory."""
    store = SampleStorage(str(tmp_path / "samples"), settings.storage_key)
    monkeypatch.setattr(sample_service, "storage", store)
    monkeypatch.setattr(job_service, "storage", store)


@pytest.fixture()
def db_session() -> Iterator[Session]:
    # In-memory SQLite shared across connections for the duration of a test.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    def override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def admin(db_session: Session) -> dict[str, str]:
    user_service.create_user(db_session, "admin", "admin-password-1", Role.administrator)
    db_session.commit()
    return {"username": "admin", "password": "admin-password-1"}


def login(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def auth_header(client: TestClient, username: str, password: str) -> dict[str, str]:
    tokens = login(client, username, password)
    return {"Authorization": f"Bearer {tokens['access_token']}"}
