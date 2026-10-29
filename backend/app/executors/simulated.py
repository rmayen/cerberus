import hashlib
from time import perf_counter
from typing import Any

from app.executors.base import ExecutionRequest, ExecutionResult


class SimulatedExecutor:
    """A safe, deterministic executor for development, testing, and demos.

    It never runs the sample. Instead it derives reproducible pseudo-behaviour
    from the sample hash and the supplied environmental conditions, so the rest
    of the platform (telemetry, behaviour analysis, differential analysis) has
    real, condition-dependent signal to work with without detonating malware.
    """

    name = "simulated"

    def run(self, request: ExecutionRequest) -> ExecutionResult:
        start = perf_counter()
        observations = self._simulate(request.sample_sha256, request.conditions)
        duration_ms = int((perf_counter() - start) * 1000)
        return ExecutionResult(
            status="completed", duration_ms=duration_ms, observations=observations
        )

    @staticmethod
    def _simulate(sha256: str, conditions: dict[str, Any]) -> dict[str, Any]:
        seed = int(hashlib.sha256(sha256.encode()).hexdigest()[:8], 16)
        internet = conditions.get("internet", True)
        mutex_exists = conditions.get("existing_mutex", False)
        hostname = conditions.get("hostname", "lab-host")

        mutex_name = f"Global\\sim_{seed % 100000:05d}"

        # A sample that finds its mutex already present exits early — this is the
        # kind of environmental dependency the differential engine looks for.
        if mutex_exists:
            return {
                "conditions": conditions,
                "processes": [{"pid": 1000, "name": "sample.exe", "action": "exit_early"}],
                "network": [],
                "files_written": [],
                "mutexes_created": [],
                "notes": "mutex already present; sample exited early",
            }

        network = []
        if internet:
            c2 = f"{seed % 0xFFFF:04x}.example-c2.test"
            network = [{"type": "dns", "domain": c2}, {"type": "tcp", "dest": c2, "port": 443}]

        run_key = f"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\\sim_{seed % 1000:03d}"
        return {
            "conditions": conditions,
            "processes": [
                {"pid": 1000, "name": "sample.exe", "action": "start"},
                {"pid": 1001, "name": "child.exe", "parent": 1000, "action": "spawn"},
            ],
            "network": network,
            "files_written": [f"C:\\Users\\{hostname}\\AppData\\sim_{seed % 1000:03d}.tmp"],
            "registry_keys": [run_key],
            "persistence": [f"run_key:sim_{seed % 1000:03d}"],
            "services": [f"SimSvc_{seed % 100:02d}"],
            "scheduled_tasks": [f"\\Microsoft\\Windows\\sim_{seed % 100:02d}"],
            "mutexes_created": [mutex_name],
            "notes": "nominal simulated execution",
        }


simulated_executor = SimulatedExecutor()
