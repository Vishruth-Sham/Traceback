"""Real subprocess lifecycle test for scripts/processor_service.py.

Runs the actual start/status/stop commands against a real background
`python -m processor.scheduler` process, isolated from any real usage via
`TRACEBACK_PROCESSOR_STATE_DIR` (a tmp_path, so this never touches
.local/traceback/processor.pid) and pointed at a closed local port
(127.0.0.1:1, refuses connections immediately) so each scheduler wake fails
fast and predictably without needing a live backend. This proves the actual
process is spawned, signaled, and reaped cleanly — not just that the
Python functions behave, which tests/test_processor_scheduler.py already
covers without any subprocess.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "processor_service.py"


def _env(state_dir: Path) -> dict:
    return {
        **os.environ,
        "TRACEBACK_PROCESSOR_STATE_DIR": str(state_dir),
        "TRACEBACK_PROCESSOR_API_BASE_URL": "http://127.0.0.1:1",
        "TRACEBACK_API_TOKEN": "processor-service-test-token-only",
        "TRACEBACK_PROCESSOR_POLL_INTERVAL_S": "1",
    }


def _run(args: list[str], env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=20)


def test_start_status_stop_lifecycle(tmp_path):
    env = _env(tmp_path)
    pidfile = tmp_path / "processor.pid"
    logfile = tmp_path / "processor.log"

    status_before = _run(["status"], env)
    assert status_before.returncode == 1
    assert "not running" in status_before.stdout

    start_result = _run(["start"], env)
    assert start_result.returncode == 0
    assert "started processor scheduler" in start_result.stdout
    assert pidfile.is_file()
    pid = int(pidfile.read_text().strip())

    try:
        status_running = _run(["status"], env)
        assert status_running.returncode == 0
        assert f"pid {pid}" in status_running.stdout

        # A second start is a harmless no-op, not a duplicate process.
        second_start = _run(["start"], env)
        assert second_start.returncode == 0
        assert "already running" in second_start.stdout
        assert int(pidfile.read_text().strip()) == pid

        # Give it at least one real wake against the closed port so the log
        # shows it actually ran (and survived a failed REST call) rather
        # than dying on the first iteration.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not logfile.exists():
            time.sleep(0.2)
        assert logfile.exists()
        deadline = time.monotonic() + 5
        content = ""
        while time.monotonic() < deadline:
            content = logfile.read_text()
            if "iteration" in content or "scheduler starting" in content:
                break
            time.sleep(0.2)
        assert "scheduler starting" in content
    finally:
        stop_result = _run(["stop"], env)
        assert stop_result.returncode == 0
        assert "stopped processor scheduler" in stop_result.stdout

    assert not pidfile.is_file()

    status_after = _run(["status"], env)
    assert status_after.returncode == 1
    assert "not running" in status_after.stdout


def test_start_uses_the_venv_interpreter_even_when_invoked_with_a_bare_system_python(tmp_path):
    """Regression test: `start()` must spawn the scheduler with this
    checkout's `.venv` interpreter, not whichever interpreter happened to
    run processor_service.py itself — otherwise invoking this script with a
    bare `python3` lacking `pydantic` silently starts a child that crashes
    on import before `status` next has a chance to notice."""
    system_python = "/usr/bin/python3"
    if not Path(system_python).is_file():
        pytest.skip(f"{system_python} not present on this machine")
    probe = subprocess.run([system_python, "-c", "import pydantic"], capture_output=True)
    if probe.returncode == 0:
        pytest.skip(f"{system_python} unexpectedly has pydantic installed; this regression needs it absent")

    env = _env(tmp_path)
    result = subprocess.run([system_python, str(SCRIPT), "start"], cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    pidfile = tmp_path / "processor.pid"
    assert pidfile.is_file()
    pid = int(pidfile.read_text().strip())

    try:
        deadline = time.time() + 5
        while time.time() < deadline:
            status = _run(["status"], env)
            if status.returncode == 0:
                break
            time.sleep(0.2)
        assert status.returncode == 0, f"scheduler did not stay running; status said: {status.stdout}"
        assert f"pid {pid}" in status.stdout
    finally:
        _run(["stop"], env)


def test_stop_when_never_started_is_a_clean_no_op(tmp_path):
    env = _env(tmp_path)
    result = _run(["stop"], env)
    assert result.returncode == 0
    assert "not running" in result.stdout


def test_status_reports_stale_pidfile_distinctly(tmp_path):
    env = _env(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "processor.pid").write_text("999999999")  # implausible/dead PID

    result = _run(["status"], env)
    assert result.returncode == 1
    assert "stale pidfile" in result.stdout


def test_status_and_stop_refuse_to_treat_a_recycled_pid_as_the_scheduler(tmp_path):
    """A pidfile pointing at a live PID that is *not* our scheduler (the
    classic PID-reuse hazard for any pidfile-based daemon) must be reported
    distinctly and must never receive SIGTERM from us."""
    env = _env(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    # This test process itself is a live PID that is certainly not
    # "python -m processor.scheduler".
    (tmp_path / "processor.pid").write_text(str(os.getpid()))

    status_result = _run(["status"], env)
    assert status_result.returncode == 1
    assert "unrelated process" in status_result.stdout

    stop_result = _run(["stop"], env)
    assert stop_result.returncode == 0
    assert "unrelated process" in stop_result.stdout
    assert not (tmp_path / "processor.pid").is_file()
    # Most importantly: this test process is still alive to make this assertion.
    assert os.kill(os.getpid(), 0) is None
