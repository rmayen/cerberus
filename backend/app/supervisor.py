"""Restarts the queue worker after unexpected exits, with backoff and a crash-loop breaker.

Run with: python -m app.supervisor

The supervisor never claims or executes jobs. It starts `python -m app.worker`, forwards SIGTERM
and SIGINT to it, and restarts it after any exit that was not requested. Every restart goes through
the worker's normal claim path, so the emergency stop still blocks new work.

After MAX_RESTARTS unexpected exits within CRASH_WINDOW_SECONDS, the supervisor stops restarting
and exits with status 1. A crash loop needs a person to look at it. Restarting faster does not help.
"""

import logging
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from pathlib import Path

logger = logging.getLogger("cerberus.supervisor")

WORKER_COMMAND: Sequence[str] = (sys.executable, "-m", "app.worker")
BACKEND_ROOT = Path(__file__).resolve().parents[1]
MAX_RESTARTS = 5
CRASH_WINDOW_SECONDS = 300.0
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_MAX_SECONDS = 30.0
# Must exceed the worker's shutdown grace (15 s) plus child termination (up to 5 s).
STOP_GRACE_SECONDS = 30.0
POLL_SECONDS = 0.2


def backoff_seconds(recent_crashes: int) -> float:
    """Delay before the next restart: 1 s, 2 s, 4 s, ... capped at BACKOFF_MAX_SECONDS."""
    return min(BACKOFF_MAX_SECONDS, BACKOFF_BASE_SECONDS * 2 ** (recent_crashes - 1))


def _stop_worker(proc: subprocess.Popen[bytes], stop_grace: float) -> int:
    """Ask the worker to shut down, then kill it only if it ignores the request past the grace."""
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=stop_grace)
    except subprocess.TimeoutExpired:
        logger.error("worker did not stop within %.0f s; killing it", stop_grace)
        proc.kill()
        proc.wait()
    return proc.returncode


def supervise(
    command: Sequence[str],
    *,
    stop: threading.Event,
    max_restarts: int = MAX_RESTARTS,
    window: float = CRASH_WINDOW_SECONDS,
    backoff: Callable[[int], float] = backoff_seconds,
    stop_grace: float = STOP_GRACE_SECONDS,
    cwd: Path = BACKEND_ROOT,
) -> int:
    """Run the worker until stop is set or the crash-loop breaker trips. Returns an exit status."""
    crashes: deque[float] = deque()
    while True:
        proc = subprocess.Popen(list(command), cwd=cwd)
        logger.info("worker started (pid %s)", proc.pid)
        while proc.poll() is None and not stop.is_set():
            time.sleep(POLL_SECONDS)
        if stop.is_set():
            _stop_worker(proc, stop_grace)
            logger.info("worker stopped on request")
            return 0

        now = time.monotonic()
        crashes.append(now)
        while crashes and now - crashes[0] > window:
            crashes.popleft()
        logger.warning("worker exited unexpectedly with status %s", proc.returncode)
        if len(crashes) > max_restarts:
            logger.error(
                "worker failed %d times within %.0f s; not restarting. Investigate before "
                "starting it again.",
                len(crashes),
                window,
            )
            return 1
        delay = backoff(len(crashes))
        logger.info("restarting worker in %.0f s", delay)
        if stop.wait(delay):
            return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stop = threading.Event()

    def request_stop(signum: int, frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    return supervise(WORKER_COMMAND, stop=stop)


if __name__ == "__main__":
    sys.exit(main())
