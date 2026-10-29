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
from app.services import differential_service, emergency_service, job_service
from tests.conftest import auth_header
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


def test_stop_between_admission_and_start_cancels_job_and_fails_analysis(
    client: TestClient,
    roles: dict[str, dict[str, str]],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Admission passes. The stop commits before the baseline's start check, so the baseline is
    # cancelled without executing, and the admitted analysis is recorded as failed.
    sample_id = _sample(client, roles["analyst"], b"MZ between-admission-and-start")
    real_check = job_service.ensure_not_active
    calls = {"n": 0}

    def stop_before_start(db: Session) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            emergency_service.set_active(db, active=True, actor_id=1)
            db.commit()
        real_check(db)

    monkeypatch.setattr(job_service, "ensure_not_active", stop_before_start)
    response = _post_differential(client, roles["analyst"], sample_id)
    monkeypatch.undo()

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "failed"
    assert "not started" in body["error_message"]
    jobs = client.get("/api/v1/jobs", headers=roles["viewer"]).json()
    assert [job["status"] for job in jobs] == ["cancelled"]


def test_stop_before_variant_admission_keeps_completed_baseline(
    client: TestClient,
    roles: dict[str, dict[str, str]],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample_id = _sample(client, roles["analyst"], b"MZ before-variant")
    real_run_variant = differential_service._run_variant
    calls = {"n": 0}

    def stop_before_second_run(db, analysis, conditions, submitted_by, timeout_seconds):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 2:
            emergency_service.set_active(db, active=True, actor_id=1)
            db.commit()
        return real_run_variant(db, analysis, conditions, submitted_by, timeout_seconds)

    monkeypatch.setattr(differential_service, "_run_variant", stop_before_second_run)
    response = _post_differential(client, roles["analyst"], sample_id)
    monkeypatch.undo()

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "failed"
    assert body["error_message"] == differential_service.EMERGENCY_MID_RUN
    jobs = client.get("/api/v1/jobs", headers=roles["viewer"]).json()
    assert [job["status"] for job in jobs] == ["completed"]


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
