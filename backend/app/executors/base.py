"""Executor abstraction for analysis backends.

An executor detonates a sample under a given set of environmental conditions and
returns observations. The platform ships with a safe simulated executor; a real
disposable-VM backend (snapshot restore, network isolation, automatic cleanup,
never executing on the host) implements the same interface in an isolated lab.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ExecutionRequest:
    sample_sha256: str
    data: bytes
    conditions: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int = 60


@dataclass(frozen=True)
class ExecutionResult:
    status: str  # "completed" | "failed"
    duration_ms: int
    observations: dict[str, Any]
    error: str | None = None


@runtime_checkable
class Executor(Protocol):
    """A pluggable analysis backend."""

    name: str

    def run(self, request: ExecutionRequest) -> ExecutionResult: ...
