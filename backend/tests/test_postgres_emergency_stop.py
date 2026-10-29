"""PostgreSQL concurrency tests for the emergency stop.

These run only when CERBERUS_TEST_POSTGRES_URL points at a disposable local database named
cerberus_test. They drop and recreate the public schema, so they refuse any other target.
"""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base
from app.executors import registry
from app.executors.simulated import SimulatedExecutor
from app.models import AnalysisJob, JobStatus, Sample
from app.services import emergency_service, job_service
from app.services.emergency_service import EmergencyStopActive

BACKEND = Path(__file__).resolve().parent.parent
PG_URL = os.environ.get("CERBERUS_TEST_POSTGRES_URL", "")

pytestmark = pytest.mark.skipif(not PG_URL, reason="CERBERUS_TEST_POSTGRES_URL not set")


@pytest.fixture(scope="module")
def pg_engine():
    if not (PG_URL.endswith("/cerberus_test") and "@localhost:" in PG_URL):
        pytest.fail("refusing to run: test URL must be localhost database cerberus_test")
    engine = create_engine(PG_URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    previous = settings.database_url
    settings.database_url = PG_URL
    try:
        command.upgrade(cfg, "head")
    finally:
        settings.database_url = previous
    yield engine
    engine.dispose()


@pytest.fixture()
def make_session(pg_engine):
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    with pg_engine.begin() as conn:
        names = [t.name for t in Base.metadata.sorted_tables]
        conn.execute(text(f"TRUNCATE {', '.join(names)} CASCADE"))
        # Actor 1 is a real administrator row, so changed_by satisfies its foreign key.
        conn.execute(
            text(
                "INSERT INTO users (id, username, hashed_password, role, is_active, "
                "failed_login_count, created_at) VALUES (1, 'pg-stop-admin', 'not-a-login', "
                "'administrator', true, 0, now())"
            )
        )
        conn.execute(
            text(
                "INSERT INTO users (id, username, hashed_password, role, is_active, "
                "failed_login_count, created_at) VALUES (2, 'pg-stop-admin-2', 'not-a-login', "
                "'administrator', true, 0, now())"
            )
        )
        conn.execute(
            text(
                "INSERT INTO emergency_stop (id, active, changed_by, changed_at) "
                "VALUES (1, false, NULL, now())"
            )
        )
    return factory


def _sample(make_session, sha: str) -> int:
    with make_session() as s:
        row = Sample(
            sha256=sha, filename="s.bin", size_bytes=2, detected_type="pe", stored_path="unused"
        )
        s.add(row)
        s.commit()
        return row.id


def test_migration_seeds_switch_on_postgresql(pg_engine, make_session) -> None:
    with make_session() as s:
        assert emergency_service.is_active(s) is False


def test_activation_waits_for_inflight_admission(pg_engine, make_session) -> None:
    admit = make_session()
    emergency_service.ensure_not_active(admit)  # shared lock held, transaction open
    done = threading.Event()

    def activate() -> None:
        with make_session() as s:
            emergency_service.set_active(s, active=True, actor_id=1)
            s.commit()
        done.set()

    worker = threading.Thread(target=activate)
    worker.start()
    try:
        assert not done.wait(1.0), "activation must wait for the admission's shared lock"
    finally:
        admit.commit()
        admit.close()
    assert done.wait(10)
    worker.join(10)
    with make_session() as s, pytest.raises(EmergencyStopActive):
        emergency_service.ensure_not_active(s)


def test_activation_from_separate_process_waits_for_admission(pg_engine, make_session) -> None:
    admit = make_session()
    emergency_service.ensure_not_active(admit)
    script = (
        "import os\n"
        "from sqlalchemy import create_engine\n"
        "from sqlalchemy.orm import Session\n"
        "from app.services import emergency_service as e\n"
        "eng = create_engine(os.environ['CERBERUS_TEST_POSTGRES_URL'])\n"
        "s = Session(eng)\n"
        "e.set_active(s, active=True, actor_id=1)\n"
        "s.commit()\n"
        "eng.dispose()\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=BACKEND,
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        time.sleep(1.5)
        assert proc.poll() is None, "separate-process activation finished before admission ended"
        admit.commit()
        admit.close()
        _, err = proc.communicate(timeout=30)
        assert proc.returncode == 0, err.decode()
    finally:
        admit.rollback()
        admit.close()
        if proc.poll() is None:
            proc.kill()
    with make_session() as s, pytest.raises(EmergencyStopActive):
        emergency_service.ensure_not_active(s)


def test_admissions_under_concurrent_activation_leave_no_partial_rows(
    pg_engine, make_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(job_service.storage, "load", lambda sha: b"MZ")
    sample_id = _sample(make_session, "a" * 64)
    stop = threading.Event()
    lock = threading.Lock()
    admitted: list[int] = []
    refused: list[int] = []

    def worker() -> None:
        while not stop.is_set():
            s = make_session()
            try:
                job = job_service.create_job(
                    s,
                    sample_id=sample_id,
                    executor_name="simulated",
                    conditions={},
                    submitted_by=None,
                )
                with lock:
                    admitted.append(job.id)
            except EmergencyStopActive:
                s.rollback()
                with lock:
                    refused.append(1)
            finally:
                s.close()

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    time.sleep(0.5)
    with make_session() as s:
        emergency_service.set_active(s, active=True, actor_id=1)
        s.commit()
    time.sleep(0.5)
    stop.set()
    for t in threads:
        t.join(30)

    assert refused, "activation must refuse at least some admissions"
    with make_session() as s:
        stored = s.query(AnalysisJob).count()
    assert stored == len(admitted), "refused admissions must leave no job rows"
    with make_session() as s, pytest.raises(EmergencyStopActive):
        job_service.create_job(
            s, sample_id=sample_id, executor_name="simulated", conditions={}, submitted_by=None
        )


def test_job_stopped_between_admission_and_start_is_cancelled_without_execution(
    pg_engine, make_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(job_service.storage, "load", lambda sha: b"MZ")
    calls = {"n": 0}

    class CountingExecutor(SimulatedExecutor):
        name = "counting"

        def run(self, request):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            return super().run(request)

    monkeypatch.setitem(registry._EXECUTORS, "counting", CountingExecutor())
    sample_id = _sample(make_session, "b" * 64)
    with make_session() as admit:
        job_id = job_service.create_job(
            admit, sample_id=sample_id, executor_name="counting", conditions={}, submitted_by=None
        ).id

    with make_session() as s:
        emergency_service.set_active(s, active=True, actor_id=1)
        s.commit()

    with make_session() as run:
        job = run.get(AnalysisJob, job_id)
        assert job is not None
        job_service.run_job(run, job)
        run.commit()
        assert job.status == JobStatus.cancelled
    assert calls["n"] == 0
