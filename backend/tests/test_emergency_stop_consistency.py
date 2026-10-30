from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.database import Base
from app.services import emergency_service
from app.services.worker_service import process_next
from tests.conftest import auth_header, run_queued
from tests.test_emergency_stop import _sample, _set_stop, roles  # noqa: F401  (fixture reuse)

BACKEND = Path(__file__).resolve().parent.parent


def _post_differential(client: TestClient, headers: dict[str, str], sample_id: int) -> object:
    return client.post(
        "/api/v1/differential",
        json={
            "sample_id": sample_id,
            "baseline_conditions": {"internet": True},
            "variations": [{"internet": False}],
        },
        headers=headers,
    )


def test_stop_after_admission_keeps_queued_runs_pending(
    client: TestClient,
    roles: dict[str, dict[str, str]],  # noqa: F811
) -> None:
    sample_id = _sample(client, roles["analyst"], b"MZ queued-stop")
    analysis_id = _post_differential(client, roles["analyst"], sample_id).json()["id"]
    _set_stop(client, roles["admin"], True)

    assert run_queued() == 0  # workers claim nothing while the stop is active
    body = client.get(f"/api/v1/differential/{analysis_id}", headers=roles["viewer"]).json()
    assert body["status"] == "pending"
    assert body["findings"] == []

    _set_stop(client, roles["admin"], False)
    assert run_queued() == 2
    body = client.get(f"/api/v1/differential/{analysis_id}", headers=roles["viewer"]).json()
    assert body["status"] == "completed"


def test_stop_between_runs_preserves_completed_baseline(
    client: TestClient,
    roles: dict[str, dict[str, str]],  # noqa: F811
    db_session: Session,
) -> None:
    sample_id = _sample(client, roles["analyst"], b"MZ between-runs")
    analysis_id = _post_differential(client, roles["analyst"], sample_id).json()["id"]

    # Run only the oldest queued job (the baseline), as a worker would before the stop.
    assert process_next(db_session, owner="test-worker") is not None
    _set_stop(client, roles["admin"], True)
    assert run_queued() == 0

    jobs = client.get(f"/api/v1/jobs?sample_id={sample_id}", headers=roles["viewer"]).json()
    assert sorted(job["status"] for job in jobs) == ["completed", "pending"]
    body = client.get(f"/api/v1/differential/{analysis_id}", headers=roles["viewer"]).json()
    assert body["status"] == "running"  # one child claimed; the analysis is in progress

    _set_stop(client, roles["admin"], False)
    assert run_queued() == 1
    body = client.get(f"/api/v1/differential/{analysis_id}", headers=roles["viewer"]).json()
    assert body["status"] == "completed"


def test_last_administrator_change_wins(
    client: TestClient,
    roles: dict[str, dict[str, str]],  # noqa: F811
    admin: dict[str, str],
) -> None:
    client.post(
        "/api/v1/users",
        json={
            "username": "stop-admin-2",
            "password": "stop-admin-2-pass-1",
            "role": "administrator",
        },
        headers=roles["admin"],
    )
    second = auth_header(client, "stop-admin-2", "stop-admin-2-pass-1")

    _set_stop(client, roles["admin"], True)
    _set_stop(client, second, False)
    assert client.get("/api/v1/emergency-stop", headers=roles["viewer"]).json() == {"active": False}


def test_switch_queries_request_row_locks_on_postgresql() -> None:
    # Evidence of intent only. These queries are not run against PostgreSQL in this environment.
    dialect = postgresql.dialect()
    shared = str(emergency_service._switch_query(exclusive=False).compile(dialect=dialect))
    exclusive = str(emergency_service._switch_query(exclusive=True).compile(dialect=dialect))
    assert "FOR SHARE" in shared
    assert "FOR UPDATE" in exclusive


def test_stop_survives_engine_restart(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'restart.db'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        emergency_service.set_active(session, active=True, actor_id=1)
        session.commit()
    engine.dispose()

    restarted = create_engine(url)
    with Session(restarted) as session:
        assert emergency_service.is_active(session) is True
    restarted.dispose()


def test_migration_seeds_off_and_downgrade_removes_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"sqlite:///{tmp_path / 'stop-migrate.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))

    command.upgrade(cfg, "head")
    engine = create_engine(url)
    with Session(engine) as session:
        assert emergency_service.is_active(session) is False
        assert session.execute(select(models.EmergencyStop.id)).scalars().all() == [1]

    command.downgrade(cfg, "3c9d1e7a5b20")
    assert "emergency_stop" not in inspect(engine).get_table_names()
    engine.dispose()
