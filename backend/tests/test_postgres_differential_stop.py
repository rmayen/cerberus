# ruff: noqa: F811  (pytest fixtures are imported from the PostgreSQL emergency-stop module)
"""PostgreSQL tests for emergency-stop activation during differential analysis.

Run only against the disposable localhost database named cerberus_test, as configured by
CERBERUS_TEST_POSTGRES_URL. Skipped otherwise.
"""

import threading
import time

import pytest
from sqlalchemy import text

from app.executors import registry
from app.executors.base import ExecutionRequest
from app.executors.simulated import SimulatedExecutor
from app.models import AnalysisJob, DifferentialAnalysis, DifferentialFinding, JobStatus
from app.services import differential_service, emergency_service, job_service
from app.services.emergency_service import EmergencyStopActive
from tests.test_postgres_emergency_stop import (  # noqa: F401  (fixtures)
    PG_URL,
    _sample,
    make_session,
    pg_engine,
)

pytestmark = pytest.mark.skipif(not PG_URL, reason="CERBERUS_TEST_POSTGRES_URL not set")


class GatedExecutor(SimulatedExecutor):
    """Harmless simulated executor. Its baseline run blocks until the test releases it."""

    name = "gated"

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def run(self, request: ExecutionRequest):  # type: ignore[no-untyped-def]
        self.calls += 1
        if request.conditions.get("gate") == "baseline":
            self.started.set()
            self.release.wait(20)
        return super().run(request)


def test_activation_during_baseline_run_stops_variant_without_blocking(
    pg_engine, make_session, monkeypatch
) -> None:
    monkeypatch.setattr(job_service.storage, "load", lambda sha: b"MZ")
    gated = GatedExecutor()
    monkeypatch.setitem(registry._EXECUTORS, "gated", gated)
    sample_id = _sample(make_session, "c" * 64)
    result: dict[str, object] = {}

    def submit() -> None:
        with make_session() as s:
            analysis = differential_service.run_differential(
                s,
                sample_id=sample_id,
                baseline_conditions={"gate": "baseline"},
                variations=[{"internet": False}],
                executor_name="gated",
                submitted_by=None,
                timeout_seconds=30,
            )
            result["status"] = analysis.status
            result["error"] = analysis.error_message
            result["id"] = analysis.id

    worker = threading.Thread(target=submit)
    worker.start()
    try:
        assert gated.started.wait(10), "baseline run never started"
        # The baseline is executing. Activation must commit now, without waiting for it.
        began = time.monotonic()
        with make_session() as s:
            emergency_service.set_active(s, active=True, actor_id=1)
            s.commit()
        assert time.monotonic() - began < 5, "activation blocked behind a running analysis"
    finally:
        gated.release.set()
    worker.join(30)

    assert result["status"] == JobStatus.failed
    assert result["error"] == differential_service.EMERGENCY_MID_RUN
    assert gated.calls == 1, "no variant run may execute after activation"
    with make_session() as s:
        jobs = s.query(AnalysisJob).order_by(AnalysisJob.id).all()
        assert [j.status for j in jobs] == [JobStatus.completed]
        assert s.query(DifferentialFinding).count() == 0


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
                differential_service.run_differential(
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
        assert all(a.status in (JobStatus.completed, JobStatus.failed) for a in analyses)
        for analysis in analyses:
            count = s.query(DifferentialFinding).filter_by(analysis_id=analysis.id).count()
            if analysis.status == JobStatus.failed:
                assert count == 0, "failed analyses must not carry findings"
        active_jobs = (
            s.query(AnalysisJob)
            .filter(AnalysisJob.status.in_([JobStatus.pending, JobStatus.running]))
            .count()
        )
        assert active_jobs == 0
    with make_session() as s, pytest.raises(EmergencyStopActive):
        differential_service.run_differential(
            s,
            sample_id=sample_id,
            baseline_conditions={},
            variations=[{"internet": False}],
            executor_name="simulated",
            submitted_by=None,
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
