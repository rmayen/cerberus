from app.executors.base import ExecutionRequest
from app.executors.registry import UnknownExecutor, get_executor
from app.executors.simulated import SimulatedExecutor


def _run(conditions: dict[str, object]):
    return SimulatedExecutor().run(
        ExecutionRequest(sample_sha256="a" * 64, data=b"MZ", conditions=conditions)
    )


def test_simulated_execution_is_deterministic() -> None:
    a = _run({"internet": True})
    b = _run({"internet": True})
    assert a.status == "completed"
    assert a.observations == b.observations


def test_internet_condition_changes_network_behaviour() -> None:
    online = _run({"internet": True})
    offline = _run({"internet": False})
    assert online.observations["network"]  # contacts a host when online
    assert offline.observations["network"] == []  # nothing when offline


def test_existing_mutex_causes_early_exit() -> None:
    result = _run({"existing_mutex": True})
    assert result.observations["notes"] == "mutex already present; sample exited early"
    assert result.observations["processes"][0]["action"] == "exit_early"


def test_registry_resolves_default_and_rejects_unknown() -> None:
    assert get_executor("simulated").name == "simulated"
    try:
        get_executor("nope")
    except UnknownExecutor:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected UnknownExecutor")
