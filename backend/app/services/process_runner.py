"""Runs one executor in a child process, with bounded termination and verified cleanup.

Guarantees, on POSIX:
- Execution never runs inside the worker process, so a hung or crashing executor cannot block or
  kill the worker's own thread.
- The child leads its own process group. Termination signals the whole group, so grandchildren
  do not outlive the job.
- A timeout or cancellation sends SIGTERM, waits GRACE_SECONDS, then sends SIGKILL. The outcome is
  "timed_out" or "cancelled" only after the group is confirmed gone. If it cannot be confirmed, the
  outcome is "failed" with a message saying so.

Not a security sandbox. The child runs as the same user with the same filesystem access, so this
bounds time and process lifetime only. It does not contain hostile code.
Windows has no process groups here: only the child process itself is terminated, and orphaned
grandchildren are not detected. See the README for platform limits.
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GRACE_SECONDS = 5.0
POLL_SECONDS = 0.05
POSIX = os.name == "posix"
BACKEND_ROOT = Path(__file__).resolve().parents[2]


class CancelSignal:
    """Thread-safe request to stop the running child. The first reason given is kept."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self.reason: str | None = None

    def set(self, reason: str) -> None:
        if self.reason is None:
            self.reason = reason
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()


@dataclass(frozen=True)
class Outcome:
    kind: str  # "completed" | "failed" | "timed_out" | "cancelled"
    error: str | None = None
    observations: dict[str, Any] | None = None
    duration_ms: int = 0
    pid: int | None = None


def run_in_child(
    *,
    executor_name: str,
    sample_sha256: str,
    conditions: dict[str, Any],
    timeout_seconds: int,
    cancel: CancelSignal | None = None,
) -> Outcome:
    cancel = cancel or CancelSignal()
    request = json.dumps(
        {
            "executor": executor_name,
            "sample_sha256": sample_sha256,
            "conditions": conditions,
            "timeout_seconds": timeout_seconds,
            "parent_pid": os.getpid(),  # the child stops itself if this process dies
        }
    ).encode()
    # Temporary files, not pipes, so a large result cannot block the child while we wait on it.
    with tempfile.TemporaryFile() as stdin, tempfile.TemporaryFile() as stdout:
        stdin.write(request)
        stdin.seek(0)
        proc = subprocess.Popen(
            [sys.executable, "-m", "app.executors.child"],
            stdin=stdin,
            stdout=stdout,
            stderr=subprocess.DEVNULL,
            cwd=BACKEND_ROOT,
            start_new_session=POSIX,
            close_fds=True,
        )
        deadline = time.monotonic() + timeout_seconds
        stop_reason: str | None = None
        while not _exited(proc):
            if cancel.is_set():
                stop_reason = "cancelled"
                break
            if time.monotonic() >= deadline:
                stop_reason = "timed_out"
                break
            time.sleep(POLL_SECONDS)

        if stop_reason is not None:
            if not _terminate(proc):
                return Outcome(
                    "failed", "could not confirm the executor process stopped", pid=proc.pid
                )
            if stop_reason == "timed_out":
                return Outcome("timed_out", "execution exceeded timeout", pid=proc.pid)
            return Outcome("cancelled", cancel.reason or "cancelled while running", pid=proc.pid)

        # The child exited on its own. Remove any grandchildren it left in its group.
        if not _terminate(proc, graceful=False):
            return Outcome("failed", "could not confirm the executor process stopped", pid=proc.pid)
        stdout.seek(0)
        return _parse(proc.returncode, stdout.read(), proc.pid)


def _exited(proc: subprocess.Popen[bytes]) -> bool:
    """True once the leader has exited. On POSIX the leader is NOT reaped, so its pid stays
    reserved and cannot be reused while the group is signalled. Reaping happens only in _terminate,
    after the group sweep. Otherwise a reused pid could receive the SIGKILL meant for this group.
    """
    if sys.platform != "win32":
        # Typeshed omits waitid on some POSIX platforms; it exists on macOS and Linux at runtime.
        waitid: Any = os.waitid  # type: ignore[attr-defined,unused-ignore]
        return waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
    return proc.poll() is not None


def _parse(returncode: int, raw: bytes, pid: int) -> Outcome:
    if returncode != 0:
        return Outcome("failed", "executor process exited unexpectedly", pid=pid)
    try:
        payload = json.loads(raw)
        status = payload["status"]
        observations = payload["observations"]
        duration_ms = int(payload.get("duration_ms", 0))
    except (ValueError, KeyError, TypeError):
        return Outcome("failed", "executor returned an invalid result", pid=pid)
    kind = "completed" if status == "completed" else "failed"
    return Outcome(kind, payload.get("error"), observations, duration_ms, pid)


def _signal_group(proc: subprocess.Popen[bytes], *, kill: bool) -> None:
    """POSIX: signal the whole process group. Windows: TerminateProcess on the leader only."""
    if not POSIX:
        if kill:
            proc.kill()
        else:
            proc.terminate()
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL if kill else signal.SIGTERM)
    except ProcessLookupError:
        pass
    except PermissionError:
        # macOS returns EPERM when the group leader is an unreaped zombie with no signalable
        # members. A group owned by another user is never signalled, so this cannot hit it.
        pass


def _group_gone(proc: subprocess.Popen[bytes]) -> bool:
    """Called only after the leader was reaped, so the pid may be reused once the group is empty.
    A group that exists but cannot be signalled (EPERM) is treated as still present.
    """
    if not POSIX:
        return proc.poll() is not None
    try:
        os.killpg(proc.pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def _terminate(proc: subprocess.Popen[bytes], *, graceful: bool = True) -> bool:
    """Stop the child's whole group. Returns True only once the group is confirmed gone.

    The leader is signalled and not reaped until the group sweep is done (see _exited). Windows
    has no grace period: TerminateProcess is immediate, and only the leader is confirmed.
    """
    if graceful and POSIX and not _exited(proc):
        _signal_group(proc, kill=False)
        deadline = time.monotonic() + GRACE_SECONDS
        while not _exited(proc) and time.monotonic() < deadline:
            time.sleep(POLL_SECONDS)
    elif graceful and not POSIX and proc.poll() is None:
        _signal_group(proc, kill=False)
        try:
            proc.wait(timeout=GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            pass
    _signal_group(proc, kill=True)  # sweeps grandchildren even when the leader already exited
    proc.wait()  # reap the leader; SIGKILL cannot be caught, so this returns promptly
    deadline = time.monotonic() + GRACE_SECONDS
    while not _group_gone(proc):
        if time.monotonic() >= deadline:
            return False
        time.sleep(POLL_SECONDS)
        _signal_group(proc, kill=True)
    return True
