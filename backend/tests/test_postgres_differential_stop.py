# ruff: noqa: F811  (pytest fixtures are imported from the PostgreSQL emergency-stop module)
"""PostgreSQL tests for emergency-stop activation during differential analysis.

Run only against the disposable localhost database named cerberus_test, as configured by
CERBERUS_TEST_POSTGRES_URL. Skipped otherwise.
"""

import threading
import time

import pytest
from sqlalchemy import text

from app.models import AnalysisJob, DifferentialAnalysis, DifferentialFinding, JobStatus
from app.services import differential_service, emergency_service, job_service
from app.services.emergency_service import EmergencyStopActive
from app.services.worker_service import drain
from tests.test_postgres_emergency_stop import (  # noqa: F401  (fixtures)
    PG_URL,
    _sample,
    make_session,
    pg_engine,
)

pytestmark = pytest.mark.skipif(not PG_URL, reason="CERBERUS_TEST_POSTGRES_URL not set")


def test_activation_during_baseline_run_stops_queued_variants_without_blocking(
    pg_engine, make_session, monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(job_service.storage, "load", lambda sha: b"MZ")
    gate = tmp_path / "gate"  # the child run waits for this file; the test creates it to release
    log = tmp_path / "runs.log"
    sample_id = _sample(make_session, "c" * 64)
    with make_session() as s:
        analysis_id = differential_service.enqueue(
            s,
            sample_id=sample_id,
            baseline_conditions={"gate_file": str(gate), "log": str(log)},
            variations=[{"internet": False}],
            executor_name="gated",
            submitted_by=None,
            timeout_seconds=30,
        ).id
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            with make_session() as s:
                drain(s, owner="w1")  # claims the gated baseline, then tries the variant
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    try:
        started = gate.with_name("gate.started")
        deadline = time.monotonic() + 10
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert started.exists(), "baseline run never started"
        # The baseline is executing. Activation must commit now, without waiting for it.
        began = time.monotonic()
        with make_session() as s:
            emergency_service.set_active(s, active=True, actor_id=1)
            s.commit()
        assert time.monotonic() - began < 5, "activation blocked behind a running analysis"
    finally:
        gate.touch()
    thread.join(30)
    assert errors == []

    assert log.read_text().count("run") == 1, "no variant may start after activation"
    with make_session() as s:
        jobs = s.query(AnalysisJob).filter_by(differential_id=analysis_id).order_by(AnalysisJob.id)
        assert [j.status for j in jobs] == [JobStatus.completed, JobStatus.pending]
        analysis = s.get(DifferentialAnalysis, analysis_id)
        assert analysis.status == JobStatus.running  # queued work preserved, not failed
        assert s.query(DifferentialFinding).count() == 0
        assert differential_service.finalize_ready(s) == 0  # the variant is still queued


def test_concurrent_differential_submissions_end_in_consistent_terminal_states(
    pg_engine, make_session, monkeypatch
) -> None:
    monkeypatch.setattr(job_service.storage, "load", lambda sha: b"MZ")
    sample_id = _sample(make_session, "d" * 64)
    stop = threading.Event()
    refused: list[int] = []
    lock = threading.Lock()

    def submit() -> None:
        while not stop.is_set():
            s = make_session()
            try:
                differential_service.enqueue(
                    s,
                    sample_id=sample_id,
                    baseline_conditions={"internet": True},
                    variations=[{"internet": False}],
                    executor_name="simulated",
                    submitted_by=None,
                )
            except EmergencyStopActive:
                s.rollback()
                with lock:
                    refused.append(1)
            finally:
                s.close()

    threads = [threading.Thread(target=submit) for _ in range(4)]
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

    with make_session() as s:
        analyses = s.query(DifferentialAnalysis).all()
        assert analyses, "some analyses should have been admitted before activation"
        for analysis in analyses:  # every admitted analysis has its full set of child jobs
            jobs = s.query(AnalysisJob).filter_by(differential_id=analysis.id).all()
            assert len(jobs) == 2
        assert all(a.status == JobStatus.pending for a in analyses)
        assert refused, "admissions during the stop must be refused"

    with make_session() as s:  # stop cleared by a fresh administrator change
        emergency_service.set_active(s, active=False, actor_id=1)
        s.commit()
    with make_session() as s:
        drain(s, owner="w1")
    with make_session() as s:  # finalize_ready handles a bounded batch per call, as the worker does
        while differential_service.finalize_ready(s):
            pass
    with make_session() as s:
        statuses = [a.status for a in s.query(DifferentialAnalysis).all()]
        assert statuses and all(st == JobStatus.completed for st in statuses)
        assert (
            s.query(AnalysisJob)
            .filter(AnalysisJob.status.in_([JobStatus.pending, JobStatus.running]))
            .count()
            == 0
        )


def test_two_administrators_changing_stop_leave_consistent_state(pg_engine, make_session) -> None:
    errors: list[BaseException] = []

    def toggle(actor_id: int, value: bool) -> None:
        try:
            for _ in range(20):
                with make_session() as s:
                    emergency_service.set_active(s, active=value, actor_id=actor_id)
                    s.commit()
        except BaseException as exc:  # surfaced below
            errors.append(exc)

    first = threading.Thread(target=toggle, args=(1, True))
    second = threading.Thread(target=toggle, args=(2, False))
    first.start()
    second.start()
    first.join(60)
    second.join(60)
    assert not errors, errors

    with make_session() as s:
        row = s.execute(text("SELECT active, changed_by FROM emergency_stop WHERE id = 1")).one()
    # Each write sets active and changed_by together, so the pair must match one writer.
    assert (row.active, row.changed_by) in {(True, 1), (False, 2)}
