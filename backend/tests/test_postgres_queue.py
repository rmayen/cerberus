# ruff: noqa: F811
"""PostgreSQL concurrency tests for the worker queue.

Run only against the disposable localhost database cerberus_test (CERBERUS_TEST_POSTGRES_URL).
"""

import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.models import AnalysisJob, JobStatus
from app.services import job_service
from app.services.worker_service import (
    RECOVERY_MESSAGE,
    LeaseHeartbeat,
    claim_next,
    recover_expired_leases,
    renew_lease,
)
from tests.test_postgres_emergency_stop import (  # noqa: F401  (fixtures)
    PG_URL,
    _sample,
    make_session,
    pg_engine,
)

pytestmark = pytest.mark.skipif(not PG_URL, reason="CERBERUS_TEST_POSTGRES_URL not set")


def test_concurrent_workers_never_claim_the_same_job(
    pg_engine: Any, make_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample_id = _sample(make_session, "e" * 64)
    with make_session() as s:
        queued = [
            job_service.create_job(
                s, sample_id=sample_id, executor_name="simulated", conditions={}, submitted_by=None
            ).id
            for _ in range(12)
        ]

    claimed: list[int] = []
    lock = threading.Lock()

    def worker(owner: str) -> None:
        while True:
            with make_session() as s:
                job_id = claim_next(s, owner=owner, lease=timedelta(seconds=90))
            if job_id is None:
                return
            with lock:
                claimed.append(job_id)

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)

    assert sorted(claimed) == sorted(queued), "every job claimed exactly once"
    assert len(claimed) == len(set(claimed))


def test_claim_racing_cancel_has_exactly_one_outcome(
    pg_engine: Any, make_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample_id = _sample(make_session, "f" * 64)
    for _ in range(10):
        with make_session() as s:
            job_id = job_service.create_job(
                s, sample_id=sample_id, executor_name="simulated", conditions={}, submitted_by=None
            ).id

        results: dict[str, Any] = {}
        start = threading.Barrier(2)

        def claimer(job_id: int, start: threading.Barrier, results: dict[str, Any]) -> None:
            start.wait()
            with make_session() as s:
                results["claimed"] = claim_next(s, owner="w1", lease=timedelta(seconds=90))

        def canceller(job_id: int, start: threading.Barrier, results: dict[str, Any]) -> None:
            start.wait()
            with make_session() as s:
                _, outcome = job_service.cancel_queued(s, job_id)
                results["cancel"] = outcome

        threads = [
            threading.Thread(target=claimer, args=(job_id, start, results)),
            threading.Thread(target=canceller, args=(job_id, start, results)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)

        claimed_it = results["claimed"] == job_id
        cancelled_it = results["cancel"] == "cancelled"
        assert claimed_it != cancelled_it, results
        if claimed_it:
            assert results["cancel"] == "not_cancellable"
        else:
            assert results["claimed"] is None


def _claimed(make_session: Any, sample_id: int, owner: str, lease: timedelta) -> int:
    with make_session() as s:
        job_id = job_service.create_job(
            s, sample_id=sample_id, executor_name="simulated", conditions={}, submitted_by=None
        ).id
    with make_session() as s:
        assert claim_next(s, owner=owner, lease=lease) == job_id
    return job_id


def _status(make_session: Any, job_id: int) -> tuple[JobStatus, str | None, str | None]:
    with make_session() as s:
        job = s.get(AnalysisJob, job_id)
        return job.status, job.lease_owner, job.error


def test_heartbeat_renews_active_lease_and_keeps_ownership(
    pg_engine: Any, make_session: Any
) -> None:
    sample_id = _sample(make_session, "1" * 64)
    job_id = _claimed(make_session, sample_id, "w1", timedelta(milliseconds=400))

    with LeaseHeartbeat(
        make_session,
        job_id,
        owner="w1",
        lease=timedelta(milliseconds=400),
        interval=timedelta(milliseconds=50),
    ):
        time.sleep(1.0)  # well past the original lease; only renewals keep it live
        with make_session() as s:
            assert recover_expired_leases(s) == 0

    assert _status(make_session, job_id) == (JobStatus.running, "w1", None)
    with make_session() as s:
        assert recover_expired_leases(s, now=datetime.now(UTC) + timedelta(seconds=5)) == 1


def test_renewal_is_refused_after_recovery(pg_engine: Any, make_session: Any) -> None:
    sample_id = _sample(make_session, "2" * 64)
    job_id = _claimed(make_session, sample_id, "w1", timedelta(milliseconds=100))
    time.sleep(0.25)
    with make_session() as s:
        assert recover_expired_leases(s) == 1

    with make_session() as s:
        assert renew_lease(s, job_id, owner="w1") is False
    status, _, error = _status(make_session, job_id)
    assert status == JobStatus.failed
    assert error == RECOVERY_MESSAGE


def test_stale_worker_cannot_commit_after_its_lease_expired(
    pg_engine: Any, make_session: Any
) -> None:
    sample_id = _sample(make_session, "3" * 64)
    job_id = _claimed(make_session, sample_id, "stale", timedelta(seconds=-1))  # already expired
    with make_session() as s:
        job = s.get(AnalysisJob, job_id)
        job_service._settle(s, job, "stale", JobStatus.completed, error=None)  # not recovered yet

    assert _status(make_session, job_id)[0] == JobStatus.running

    with make_session() as s:
        assert recover_expired_leases(s) == 1
    with make_session() as s:
        job = s.get(AnalysisJob, job_id)
        job_service._settle(s, job, "stale", JobStatus.completed, error=None)  # after recovery

    assert _status(make_session, job_id)[:1] == (JobStatus.failed,)


def test_heartbeat_and_recovery_do_not_race_a_live_job(pg_engine: Any, make_session: Any) -> None:
    sample_id = _sample(make_session, "4" * 64)
    job_id = _claimed(make_session, sample_id, "w1", timedelta(milliseconds=300))

    recovered = 0
    with LeaseHeartbeat(
        make_session,
        job_id,
        owner="w1",
        lease=timedelta(milliseconds=300),
        interval=timedelta(milliseconds=20),
    ):
        for _ in range(40):  # independent recovery sessions run while renewals continue
            with make_session() as s:
                recovered += recover_expired_leases(s)
            time.sleep(0.02)

    assert recovered == 0
    assert _status(make_session, job_id)[:2] == (JobStatus.running, "w1")


def test_renewal_and_recovery_racing_on_the_same_expiring_lease(
    pg_engine: Any, make_session: Any
) -> None:
    sample_id = _sample(make_session, "5" * 64)
    errors: list[BaseException] = []
    for round_number in range(15):
        job_id = _claimed(make_session, sample_id, "w1", timedelta(milliseconds=50))
        time.sleep(0.04)  # the lease is about to expire
        outcome: dict[str, Any] = {}
        start = threading.Barrier(2)

        def renewer(job_id: int, start: threading.Barrier, outcome: dict[str, Any]) -> None:
            try:
                start.wait()
                with make_session() as s:
                    outcome["renewed"] = renew_lease(
                        s, job_id, owner="w1", lease=timedelta(milliseconds=50)
                    )
            except BaseException as exc:  # surfaced after the join
                errors.append(exc)

        def recoverer(start: threading.Barrier, outcome: dict[str, Any]) -> None:
            try:
                start.wait()
                with make_session() as s:
                    outcome["recovered"] = recover_expired_leases(s)
            except BaseException as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=renewer, args=(job_id, start, outcome)),
            threading.Thread(target=recoverer, args=(start, outcome)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)

        assert not (outcome["renewed"] and outcome["recovered"]), (round_number, outcome)
        status, _, error = _status(make_session, job_id)
        if outcome["recovered"]:
            assert status == JobStatus.failed and error == RECOVERY_MESSAGE
        else:
            assert status == JobStatus.running
            with make_session() as s:
                assert recover_expired_leases(s, now=datetime.now(UTC) + timedelta(seconds=5)) == 1

    assert errors == []
