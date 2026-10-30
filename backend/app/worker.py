"""Worker process for queued simulated jobs.

Run with: python -m app.worker
Health check: python -m app.worker --check (exit 0 while this worker reports ready and is alive).
Requires PostgreSQL (CERBERUS_DATABASE_URL); other databases are refused at startup.

Each loop recovers expired leases, then processes queued jobs until none can be claimed. The
emergency stop blocks new claims but does not terminate running work.

Shutdown: SIGTERM or SIGINT stops new claims. A running job may finish for SHUTDOWN_GRACE_SECONDS,
then its child is terminated and the job is recorded cancelled. Restarts are handled by
app.supervisor, which uses the same claim path, so the emergency stop still applies.
"""

import importlib
import json
import os
import signal
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType

from app.config import ConfigurationError, settings
from app.database import SessionLocal
from app.services.differential_service import finalize_ready
from app.services.worker_service import drain, recover_expired_leases

POLL_SECONDS = 2.0
STATE_READY = "ready"
STATE_STOPPING = "stopping"

shutdown = threading.Event()


def require_postgresql(database_url: str) -> None:
    """Refuse to run the queue worker on any database that cannot enforce claiming guarantees."""
    if not database_url.startswith("postgresql"):
        raise ConfigurationError(
            "the job queue worker requires PostgreSQL (CERBERUS_DATABASE_URL must start with "
            "postgresql); SQLite cannot enforce claiming, cancellation, or lease guarantees"
        )


def write_status(state: str, path: Path) -> None:
    """Atomically record the worker state. Contains only the state, pid, and a timestamp."""
    payload = {"state": state, "pid": os.getpid(), "updated_at": datetime.now(UTC).isoformat()}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload))
    os.replace(tmp, path)


def check_status(path: Path) -> bool:
    """True when the file says ready and the recorded process still exists (POSIX).

    The file is written only after startup succeeds, and set to stopping on exit. A crashed worker
    leaves ready behind, so the pid check is what detects it. Windows relies on the state alone.
    """
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict) or data.get("state") != STATE_READY:
        return False
    pid = data.get("pid")
    if not isinstance(pid, int):
        return False
    if os.name == "posix":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            pass  # the process exists but belongs to someone else; only this user runs workers
    return True


def request_shutdown(signum: int, frame: FrameType | None) -> None:
    shutdown.set()


def main() -> None:
    require_postgresql(settings.database_url)
    # The worker validates executor names too, so it loads the same test-only modules as the child.
    for module in settings.executor_module_names:
        importlib.import_module(module)
    status_path = Path(settings.worker_status_file)
    owner = f"worker-{os.getpid()}"
    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    with SessionLocal() as db:
        recover_expired_leases(db)  # also proves the database is reachable before readiness
    write_status(STATE_READY, status_path)
    try:
        while not shutdown.is_set():
            with SessionLocal() as db:
                recover_expired_leases(db)
                drain(db, owner=owner, session_factory=SessionLocal, shutdown=shutdown)
                finalize_ready(db)
            shutdown.wait(POLL_SECONDS)
    finally:
        try:
            write_status(STATE_STOPPING, status_path)
        except OSError:
            pass  # a status file that cannot be written must not hide the real exit reason


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(0 if check_status(Path(settings.worker_status_file)) else 1)
    main()
