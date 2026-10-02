"""Manage the local Traceback stack for the macOS launcher apps."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / ".local" / "traceback"
VENV = ROOT / ".venv" / "bin"
API_URL = "http://127.0.0.1:8000/api/v1/health/live"
UI_URL = "http://localhost:3000/api/v1/health/ready"


def run(*args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, text=True, check=True, capture_output=capture)


def healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return response.status == 200 and json.load(response).get("status") in {"ok", "ready"}
    except (OSError, ValueError, urllib.error.URLError):
        return False


def port_busy(port: int) -> bool:
    for host in ("127.0.0.1", "::1"):
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            pass
    return False


def process_stamp(pid: int) -> str | None:
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "lstart="], text=True, capture_output=True
    )
    return result.stdout.strip() if result.returncode == 0 else None


def owned_process(name: str) -> int | None:
    path = STATE / f"{name}.pid"
    try:
        saved = json.loads(path.read_text())
        pid = int(saved["pid"])
        return pid if process_stamp(pid) == saved["stamp"] else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def start_server(name: str, command: list[str], url: str, port: int, cwd: Path) -> None:
    if healthy(url):
        print(f"{name} already running")
        return
    if port_busy(port):
        raise RuntimeError(f"Port {port} is occupied by a different service; {name} was not started.")

    log_path = STATE / f"{name}.log"
    with log_path.open("ab") as log:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env={**os.environ, "PATH": f"/opt/homebrew/bin:/usr/local/bin:{os.environ.get('PATH', '')}"},
        )
    stamp = process_stamp(process.pid)
    if stamp is None:
        raise RuntimeError(f"{name} exited immediately. Check {log_path}.")
    (STATE / f"{name}.pid").write_text(json.dumps({"pid": process.pid, "stamp": stamp}))

    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if healthy(url):
            print(f"{name} ready")
            return
        if process.poll() is not None:
            break
        time.sleep(0.5)
    raise RuntimeError(f"{name} did not become ready. Check {log_path}.")


def stop_server(name: str) -> None:
    pid = owned_process(name)
    if pid is None:
        print(f"{name}: no launcher-owned process")
        return
    os.killpg(pid, signal.SIGTERM)
    for _ in range(40):
        if process_stamp(pid) is None:
            break
        time.sleep(0.25)
    (STATE / f"{name}.pid").unlink(missing_ok=True)
    print(f"{name} stopped")


def start() -> None:
    # Finder apps do not inherit the interactive shell's locale. PostgreSQL on
    # macOS can fail with "postmaster became multithreaded" without this.
    os.environ["LC_ALL"] = "C"
    os.environ["LANG"] = "C"
    if not (ROOT / ".env").is_file() or not (ROOT / "frontend" / ".env.local").is_file():
        raise RuntimeError("Missing .env or frontend/.env.local. Follow docs/local-development.md first.")
    if not (VENV / "uvicorn").exists() or not (ROOT / "frontend/node_modules/.bin/next").exists():
        raise RuntimeError("Missing dependencies. Run uv sync --locked and npm install in frontend/ first.")
    STATE.mkdir(parents=True, exist_ok=True)

    db_was_running = subprocess.run(
        [sys.executable, str(ROOT / "scripts/local_db.py"), "status"],
        cwd=ROOT, capture_output=True,
    ).returncode == 0
    try:
        run(sys.executable, str(ROOT / "scripts/local_db.py"), "start")
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"PostgreSQL could not start. Check {STATE / 'postgres.log'}.") from exc
    if not db_was_running:
        (STATE / "launcher-started-db").touch()
    run(str(VENV / "alembic"), "upgrade", "head")

    start_server(
        "api", [str(VENV / "uvicorn"), "backend.main:app", "--host", "127.0.0.1", "--port", "8000"],
        API_URL, 8000, ROOT,
    )
    start_server(
        "ui", [str(ROOT / "frontend/node_modules/.bin/next"), "dev", "--port", "3000"],
        UI_URL, 3000, ROOT / "frontend",
    )

    processor_status = subprocess.run(
        [sys.executable, str(ROOT / "scripts/processor_service.py"), "status"],
        cwd=ROOT, capture_output=True,
    ).returncode == 0
    if not processor_status:
        run(sys.executable, str(ROOT / "scripts/processor_service.py"), "start")
        (STATE / "launcher-started-processor").touch()
    print("Traceback is ready at http://localhost:3000")


def stop() -> None:
    stop_server("ui")
    stop_server("api")
    if (STATE / "launcher-started-processor").exists():
        run(sys.executable, str(ROOT / "scripts/processor_service.py"), "stop")
        (STATE / "launcher-started-processor").unlink()
    if (STATE / "launcher-started-db").exists():
        run(sys.executable, str(ROOT / "scripts/local_db.py"), "stop")
        (STATE / "launcher-started-db").unlink()


def status() -> None:
    print(f"API: {'ready' if healthy(API_URL) else 'stopped'}")
    print(f"UI: {'ready' if healthy(UI_URL) else 'stopped'}")
    subprocess.run([sys.executable, str(ROOT / "scripts/processor_service.py"), "status"], cwd=ROOT, check=False)


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"start", "stop", "status"}:
        raise SystemExit("Usage: traceback_service.py {start|stop|status}")
    try:
        {"start": start, "stop": stop, "status": status}[sys.argv[1]]()
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc
