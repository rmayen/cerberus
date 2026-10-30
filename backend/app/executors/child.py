"""Entrypoint for the executor child process. Run only by app.services.process_runner.

Reads one JSON request from stdin and writes one JSON result to stdout. The child receives the
sample hash and conditions only, never the sample bytes. Exit codes: 0 result written, 3 the
executor raised, 4 the request was invalid or the executor is unknown.

CERBERUS_EXECUTOR_MODULES (validated in app.config) names tests-package modules to import first.
Tests use this to register harmless fixture executors. Production refuses to start with it set.
"""

import importlib
import json
import sys
from typing import Any

from app.config import settings
from app.executors.base import ExecutionRequest
from app.executors.registry import UnknownExecutor, get_executor

EXIT_OK = 0
EXIT_EXECUTOR_RAISED = 3
EXIT_INVALID_REQUEST = 4


def main() -> int:
    for module in settings.executor_module_names:
        importlib.import_module(module)
    try:
        request: dict[str, Any] = json.load(sys.stdin)
        executor = get_executor(str(request["executor"]))
        execution = ExecutionRequest(
            sample_sha256=str(request["sample_sha256"]),
            data=b"",  # bytes are not passed to the child; see the module docstring
            conditions=dict(request.get("conditions") or {}),
            timeout_seconds=int(request["timeout_seconds"]),
        )
    except (KeyError, TypeError, ValueError, UnknownExecutor):
        return EXIT_INVALID_REQUEST
    try:
        result = executor.run(execution)
    except Exception:
        return EXIT_EXECUTOR_RAISED  # no exception text: it may contain local paths
    json.dump(
        {
            "status": result.status,
            "duration_ms": result.duration_ms,
            "observations": result.observations,
            "error": result.error,
        },
        sys.stdout,
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
