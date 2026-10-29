from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.config import settings

BACKEND = Path(__file__).resolve().parent.parent
BEFORE = "8585e3a8f939"
HEAD = "3c9d1e7a5b20"


def _config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    return cfg


def test_error_message_migration_keeps_existing_rows(tmp_path, monkeypatch) -> None:
    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    cfg = _config()

    command.upgrade(cfg, BEFORE)
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO differential_analyses "
                "(sample_id, executor, baseline_conditions, status, created_at) "
                "VALUES (1, 'simulated', '{}', 'completed', '2026-10-28 00:00:00')"
            )
        )

    command.upgrade(cfg, HEAD)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT status, error_message FROM differential_analyses")).all()
    assert [tuple(row) for row in rows] == [("completed", None)]

    command.downgrade(cfg, BEFORE)
    columns = {col["name"] for col in inspect(engine).get_columns("differential_analyses")}
    assert "error_message" not in columns
    engine.dispose()
