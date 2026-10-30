"""Harmless test executors, registered in the test process and imported by executor children.

They never touch sample bytes. Behaviour is chosen by the job's conditions:
- "mode": "fail" returns a failed result; "hang" sleeps past any timeout; "crash" exits the
  process; "ignore_term" ignores SIGTERM and then sleeps, so only SIGKILL stops it.
- "log": a file path. Each run appends one line, so tests can count runs across processes.
- "gate_file": the run writes "<gate>.started", then waits until the gate file exists.
Otherwise the run is the simulated executor's normal result.
"""

import os
import signal
import time
from pathlib import Path

from app.executors import registry
from app.executors.base import ExecutionRequest, ExecutionResult
from app.executors.simulated import SimulatedExecutor

GATE_WAIT_SECONDS = 20.0
HANG_SECONDS = 60.0
_simulated = SimulatedExecutor()


class FixtureExecutor:
    def __init__(self, name: str, default_mode: str | None = None) -> None:
        self.name = name
        self.default_mode = default_mode

    def run(self, request: ExecutionRequest) -> ExecutionResult:
        conditions = request.conditions
        if log := conditions.get("log"):
            with open(log, "a", encoding="utf-8") as handle:
                handle.write("run\n")
        if gate := conditions.get("gate_file"):
            Path(f"{gate}.started").touch()
            deadline = time.monotonic() + GATE_WAIT_SECONDS
            while not Path(gate).exists() and time.monotonic() < deadline:
                time.sleep(0.02)
        mode = conditions.get("mode", self.default_mode)
        if mode == "fail":
            return ExecutionResult(
                status="failed", duration_ms=0, observations={}, error="scripted failure"
            )
        if mode == "hang":
            time.sleep(HANG_SECONDS)
        if mode == "crash":
            os._exit(7)
        if mode == "ignore_term":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            time.sleep(HANG_SECONDS)
        return _simulated.run(request)


for _name, _default in (
    ("scripted", None),
    ("gated", None),
    ("recording", None),
    ("hanging", "hang"),
    ("crashing", "crash"),
    ("stubborn", "ignore_term"),
):
    registry._EXECUTORS[_name] = FixtureExecutor(_name, _default)
