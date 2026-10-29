from app.executors.base import Executor
from app.executors.simulated import simulated_executor

DEFAULT_EXECUTOR = "simulated"

_EXECUTORS: dict[str, Executor] = {
    simulated_executor.name: simulated_executor,
}


class UnknownExecutor(Exception):
    pass


def get_executor(name: str) -> Executor:
    try:
        return _EXECUTORS[name]
    except KeyError as exc:
        raise UnknownExecutor(name) from exc


def available_executors() -> list[str]:
    return sorted(_EXECUTORS)
