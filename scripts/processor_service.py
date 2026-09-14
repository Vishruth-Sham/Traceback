#!/usr/bin/env python3
"""Start/stop/status lifecycle for the local processor scheduler.

Manages one background `python -m processor.scheduler` process with a PID
file, the same self-contained pattern `scripts/local_db.py` uses for the
local PostgreSQL cluster — no launchd/systemd/cron registration, so nothing
here touches any file outside this checkout or the user's global machine
configuration. Starting is idempotent (a second `start` while already
running is a no-op); `stop` sends SIGTERM and waits for a clean exit.
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = Path(os.environ.get("TRACEBACK_PROCESSOR_STATE_DIR", str(ROOT / ".local" / "traceback")))
PIDFILE = STATE / "processor.pid"
LOGFILE = STATE / "processor.log"


def _python_executable() -> str:
    """Prefer this checkout's own venv interpreter over `sys.executable`.

    If this script itself is invoked with a bare `python3` from PATH
    (rather than an activated venv or `.venv/bin/python3`), `sys.executable`
    would be that same dependency-less interpreter, and the spawned
    `processor.scheduler` child — which needs `pydantic` — would crash
    immediately with `ModuleNotFoundError`, even though `start()` reports
    success before the child has had a chance to exit. Preferring the
    checkout's `.venv` makes `start` correct regardless of how this script
    itself was launched.
    """
    venv_python = ROOT / ".venv" / "bin" / "python3"
    return str(venv_python) if venv_python.is_file() else sys.executable


def _read_pid() -> int | None:
    if not PIDFILE.is_file():
        return None
    try:
        return int(PIDFILE.read_text().strip())
    except ValueError:
        return None


def _looks_like_our_scheduler(pid: int) -> bool:
    """Best-effort guard against a recycled PID: confirm the live process
    actually looks like `python -m processor.scheduler` before we treat a
    pidfile as current or send it a signal. If `ps` itself is unavailable
    or fails, fall back to trusting the pidfile (the previous behavior)
    rather than refusing to manage our own process."""
    try:
        output = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return True
    if output.returncode != 0:
        return True
    return "processor.scheduler" in output.stdout


def _pid_state(pid: int) -> str:
    """One of "running" (our scheduler), "dead", or "recycled" (the pid is
    alive but is a different process — the pidfile is stale and unsafe to
    signal)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "dead"
    except PermissionError:
        return "running"  # exists, just not signalable by us; treat as ours
    return "running" if _looks_like_our_scheduler(pid) else "recycled"


def _is_running(pid: int) -> bool:
    return _pid_state(pid) == "running"


def status() -> int:
    pid = _read_pid()
    if pid is None:
        print("processor scheduler is not running")
        return 1
    state = _pid_state(pid)
    if state == "running":
        print(f"processor scheduler is running (pid {pid}); log: {LOGFILE}")
        return 0
    if state == "recycled":
        print(f"processor scheduler is not running (pidfile pid {pid} now belongs to an unrelated process)")
        return 1
    print(f"processor scheduler is not running (stale pidfile for pid {pid})")
    return 1


def start() -> int:
    pid = _read_pid()
    if pid is not None and _is_running(pid):
        print(f"processor scheduler already running (pid {pid})")
        return 0
    STATE.mkdir(parents=True, exist_ok=True)
    with open(LOGFILE, "ab") as log:
        process = subprocess.Popen(
            [_python_executable(), "-m", "processor.scheduler"],
            cwd=str(ROOT),
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    PIDFILE.write_text(str(process.pid))
    print(f"started processor scheduler (pid {process.pid}); log: {LOGFILE}")
    return 0


def stop(timeout_s: float = 10.0) -> int:
    pid = _read_pid()
    if pid is None:
        print("processor scheduler is not running")
        return 0
    state = _pid_state(pid)
    if state != "running":
        reason = "now belongs to an unrelated process" if state == "recycled" else "stale"
        print(f"processor scheduler is not running (pidfile pid {pid} {reason}; clearing it)")
        PIDFILE.unlink(missing_ok=True)
        return 0
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not _is_running(pid):
            PIDFILE.unlink(missing_ok=True)
            print(f"stopped processor scheduler (pid {pid})")
            return 0
        time.sleep(0.1)
    print(f"pid {pid} did not exit within {timeout_s}s; leaving pidfile for inspection")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["start", "stop", "restart", "status"])
    args = parser.parse_args()
    if args.command == "start":
        return start()
    if args.command == "stop":
        return stop()
    if args.command == "restart":
        stop()
        return start()
    return status()


if __name__ == "__main__":
    raise SystemExit(main())
