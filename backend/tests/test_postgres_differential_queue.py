# ruff: noqa: F811
"""PostgreSQL concurrency tests for queued differential analyses.

Run only against the disposable localhost database cerberus_test (CERBERUS_TEST_POSTGRES_URL).
"""

import threading
from datetime import timedelta
from typing import Any

import pytest

from app.models import AnalysisJob, DifferentialAnalysis, JobStatus
from app.services import differential_service
from app.services.worker_service import claim_next, recover_expired_leases
from tests.test_postgres_emergency_stop import (  # noqa: F401  (fixtures)
    PG_URL,
    _sample,
    make_session,
    pg_engine,
)

pytestmark = pytest.mark.skipif(not PG_URL, reason="CERBERUS_TEST_POSTGRES_URL not set")


def _enqueue(make_session: Any, sample_id: int) -> int:
    with make_session() as s:
        return differential_service.enqueue(
            s,
            sample_id=sample_id,
            baseline_conditions={"internet": True},
            variations=[{"internet": False}],
            executor_name="simulated",
            submitted_by=None,
        ).id


def test_cancel_racing_claim_has_exactly_one_outcome(pg_engine: Any, make_session: Any) -> None:
    sample_id = _sample(make_session, "a" * 64)
    errors: list[BaseException] = []
    for _ in range(10):
        analysis_id = _enqueue(make_session, sample_id)
        outcome: dict[str, Any] = {}
        start = threading.Barrier(2)

        def claimer(start: threading.Barrier, outcome: dict[str, Any]) -> None:
            try:
                start.wait()
                with make_session() as s:
                    outcome["claimed"] = claim_next(s, owner="w1")
            except BaseException as exc:
                errors.append(exc)

        def canceller(analysis_id: int, start: threading.Barrier, outcome: dict[str, Any]) -> None:
            try:
                start.wait()
                with make_session() as s:
                    _, outcome["cancel"] = differential_service.cancel(s, analysis_id)
            except BaseException as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=claimer, args=(start, outcome)),
            threading.Thread(target=canceller, args=(analysis_id, start, outcome)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)

        # Earlier rounds leave pending children, so a claim may take another analysis's job.
        # What matters is whether this analysis's own child was claimed.
        with make_session() as s:
            claimed_here = (
                outcome["claimed"] is not None
                and s.get(AnalysisJob, outcome["claimed"]).differential_id == analysis_id
            )
            analysis = s.get(DifferentialAnalysis, analysis_id)
        assert (outcome["cancel"] == "cancelled") == (not claimed_here), outcome
        if outcome["cancel"] == "cancelled":
            assert analysis.status == JobStatus.cancelled
        else:
            assert analysis.status == JobStatus.running
    assert errors == []


def test_concurrent_finalizers_finalize_a_crashed_analysis_once(
    pg_engine: Any, make_session: Any
) -> None:
    sample_id = _sample(make_session, "b" * 64)
    analysis_id = _enqueue(make_session, sample_id)
    with make_session() as s:  # the baseline is claimed by a worker that then dies
        assert claim_next(s, owner="crashed", lease=timedelta(seconds=-1)) is not None
    with make_session() as s:  # the variant stays unclaimable while the baseline is in flight
        assert claim_next(s, owner="other") is None
    with make_session() as s:
        assert recover_expired_leases(s) == 1

    results: list[int] = []
    errors: list[BaseException] = []
    start = threading.Barrier(2)

    def finalizer(start: threading.Barrier) -> None:
        try:
            start.wait()
            with make_session() as s:
                results.append(differential_service.finalize_ready(s))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=finalizer, args=(start,)) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)

    assert errors == []
    assert sum(results) == 1  # finalized by exactly one worker
    with make_session() as s:
        analysis = s.get(DifferentialAnalysis, analysis_id)
        assert analysis.status == JobStatus.failed
        assert analysis.error_message == "Baseline run failed. The other runs were not compared."
        assert not analysis.findings
        jobs = s.query(AnalysisJob).filter(AnalysisJob.differential_id == analysis_id).all()
        assert {job.status for job in jobs} == {JobStatus.failed, JobStatus.cancelled}


def test_concurrent_workers_never_claim_a_variant_before_its_baseline_completes(
    pg_engine: Any, make_session: Any
) -> None:
    sample_id = _sample(make_session, "e" * 64)
    analysis_id = _enqueue(make_session, sample_id)
    with make_session() as s:
        baseline_id = claim_next(s, owner="baseline-holder")  # baseline is now in flight
    assert baseline_id is not None

    claims: list[int | None] = []
    errors: list[BaseException] = []
    lock = threading.Lock()
    start = threading.Barrier(4)

    def claimer(start: threading.Barrier, owner: str) -> None:
        try:
            start.wait()
            with make_session() as s:
                result = claim_next(s, owner=owner)
            with lock:
                claims.append(result)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=claimer, args=(start, f"w{i}")) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)

    assert errors == []
    assert claims == [None, None, None, None]  # no variant before the baseline completes
    with make_session() as s:
        variant = (
            s.query(AnalysisJob)
            .filter_by(differential_id=analysis_id, differential_role="variant")
            .one()
        )
        assert variant.status == JobStatus.pending
