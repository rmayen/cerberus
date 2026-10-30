"""Worker process for queued simulated jobs.

Run with: python -m app.worker
Requires PostgreSQL (CERBERUS_DATABASE_URL); other databases are refused at startup. Each loop
recovers expired leases, then processes queued jobs until none can be claimed. The emergency stop
blocks new claims but does not terminate running work.
"""

import os
import time

from app.config import ConfigurationError, settings
from app.database import SessionLocal
from app.services.differential_service import finalize_ready
from app.services.worker_service import drain, recover_expired_leases

POLL_SECONDS = 2.0


def require_postgresql(database_url: str) -> None:
    """Refuse to run the queue worker on any database that cannot enforce claiming guarantees."""
    if not database_url.startswith("postgresql"):
        raise ConfigurationError(
            "the job queue worker requires PostgreSQL (CERBERUS_DATABASE_URL must start with "
            "postgresql); SQLite cannot enforce claiming, cancellation, or lease guarantees"
        )


def main() -> None:
    require_postgresql(settings.database_url)
    owner = f"worker-{os.getpid()}"
    while True:
        with SessionLocal() as db:
            recover_expired_leases(db)
            drain(db, owner=owner, session_factory=SessionLocal)
            finalize_ready(db)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
