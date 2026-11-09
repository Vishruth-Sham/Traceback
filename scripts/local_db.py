#!/usr/bin/env python3
"""Manage a private local PostgreSQL cluster without Homebrew services or Docker."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.paths import ENV_VAR, LEGACY_DATA_DIR, data_dir, legacy_data_present, require_no_legacy_data  # noqa: E402

try:
    STATE = data_dir()
except ValueError as _error:
    raise SystemExit(f"Traceback data folder: {_error}") from None
DATA = STATE / "postgres"
ASSETS = STATE / "assets"
BIN = Path(os.environ.get("TRACEBACK_PG_BIN", "/opt/homebrew/opt/postgresql@17/bin"))
PORT = "55432"


def run(name: str, *args: str, capture: bool = False) -> str:
    env = os.environ.copy()
    credentials = STATE / "credentials.json"
    if credentials.exists():
        env["PGPASSWORD"] = json.loads(credentials.read_text())["password"]
    env.update(PGHOST="127.0.0.1", PGPORT=PORT, PGUSER="traceback", PGDATABASE="postgres")
    result = subprocess.run([str(BIN / name), *args], env=env, check=True,
                            text=True, stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else ""


def sql(query: str, database: str = "postgres") -> str:
    return run("psql", "-X", "-v", "ON_ERROR_STOP=1", "-At", "-d", database, "-c", query, capture=True)


def db_name(value: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", value):
        raise ValueError("Database names must use lowercase letters, digits, underscores (maximum 63 characters).")
    return value


def exists(name: str) -> bool:
    return sql(f"SELECT 1 FROM pg_database WHERE datname='{db_name(name)}'") == "1"


def create(name: str) -> None:
    run("createdb", db_name(name))


def running() -> bool:
    return subprocess.run([str(BIN / "pg_ctl"), "-D", str(DATA), "status"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def start() -> None:
    require_no_legacy_data(STATE)
    if not (DATA / "PG_VERSION").exists():
        raise ValueError("Cluster is not initialized; run init first.")
    if not running():
        run("pg_ctl", "-D", str(DATA), "-l", str(STATE / "postgres.log"), "-w", "start")
    sql("SELECT 1")


def init() -> None:
    require_no_legacy_data(STATE)
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    STATE.chmod(0o700)
    ASSETS.mkdir(exist_ok=True, mode=0o700)
    credentials = STATE / "credentials.json"
    if not credentials.exists():
        with open(credentials, "x", opener=lambda p, f: os.open(p, f, 0o600)) as file:
            json.dump({"password": secrets.token_urlsafe(32), "api_token": secrets.token_urlsafe(32)}, file)
    values = json.loads(credentials.read_text())
    if not (DATA / "PG_VERSION").exists():
        if DATA.exists() and any(DATA.iterdir()):
            raise ValueError("Nonempty uninitialized data directory found; inspect it manually before retrying.")
        with tempfile.NamedTemporaryFile(mode="w", dir=STATE) as password:
            password.write(values["password"] + "\n")
            password.flush()
            run("initdb", "-D", str(DATA), "-U", "traceback", "--pwfile", password.name,
                "--auth-local=scram-sha-256", "--auth-host=scram-sha-256", "--encoding=UTF8", "--locale=C")
        with (DATA / "postgresql.conf").open("a") as config:
            socket_path = str(STATE).replace("'", "''")
            config.write(f"\nlisten_addresses = '127.0.0.1'\nport = {PORT}\nunix_socket_directories = '{socket_path}'\npassword_encryption = 'scram-sha-256'\n")
    start()
    if not exists("traceback"):
        create("traceback")
    if not (ROOT / ".env").exists():
        with open(ROOT / ".env", "x", opener=lambda p, f: os.open(p, f, 0o600)) as envfile:
            envfile.write(f"TRACEBACK_DATABASE_URL=postgresql+psycopg://traceback:{values['password']}@127.0.0.1:{PORT}/traceback\nTRACEBACK_API_TOKEN={values['api_token']}\n")
    print("Local PostgreSQL ready. Existing .env files are preserved; credentials are never printed.")


def counts(database: str) -> dict[str, int]:
    tables = sql("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename", database)
    return {table: int(sql('SELECT count(*) FROM public."' + table.replace('"', '""') + '"', database))
            for table in tables.splitlines() if table}


def checksums(directory: Path) -> dict[str, str]:
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("Asset directory contains symlinks; backup/restore requires ordinary files.")
        if path.is_file():
            with path.open("rb") as stream:
                result[str(path.relative_to(directory))] = hashlib.file_digest(stream, "sha256").hexdigest()
    return result


def backup(target: Path) -> None:
    target = target.resolve()
    if target == STATE or STATE in target.parents:
        raise ValueError(f"Backup destination must be outside {STATE}.")
    # Caller stops API writes; pg_dump itself takes a consistent database snapshot.
    target.mkdir(mode=0o700, parents=True, exist_ok=False)
    run("pg_dump", "-d", "traceback", "--format=custom", "--no-owner", "--no-acl", "-f", str(target / "database.dump"))
    source_hashes = checksums(ASSETS)
    shutil.copytree(ASSETS, target / "assets")
    if checksums(target / "assets") != source_hashes:
        raise ValueError("Asset files changed during backup; backup is incomplete.")
    manifest = {"format": 1, "tables": counts("traceback"), "assets": source_hashes}
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Backup complete: {target}")


def restore(source: Path, database: str, assets: Path) -> None:
    database = db_name(database)
    if database in {"postgres", "template0", "template1", "traceback", "traceback_test"}:
        raise ValueError("Choose a separate new database name, for example traceback_restore_check.")
    manifest = json.loads((source / "manifest.json").read_text())
    if manifest.get("format") != 1 or checksums(source / "assets") != manifest["assets"]:
        raise ValueError("Backup manifest or asset checksum verification failed.")
    if exists(database) or assets.exists():
        raise ValueError("Restore requires a database and asset directory that do not already exist.")
    create(database)
    run("pg_restore", "--exit-on-error", "--single-transaction", "--no-owner", "--no-acl", "-d", database, str(source / "database.dump"))
    shutil.copytree(source / "assets", assets)
    if counts(database) != manifest["tables"] or checksums(assets) != manifest["assets"]:
        raise ValueError("Restore verification failed; retained restored data for inspection.")
    print(f"Restore verified: table row counts and asset SHA-256 checksums match ({database}).")


def pid_alive(pidfile: Path) -> bool:
    try:
        text = pidfile.read_text().strip()
        pid = int(json.loads(text)["pid"]) if text.startswith("{") else int(text)
        os.kill(pid, 0)
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return True


def move_data() -> None:
    """Move an existing in-repo data folder (.local/traceback) to the configured data folder."""
    source = LEGACY_DATA_DIR
    if not legacy_data_present():
        raise ValueError(f"Nothing to move: no Traceback data in {source}.")
    if STATE.exists():
        raise ValueError(f"{STATE} already exists; refusing to merge. Move or rename it first.")
    if subprocess.run([str(BIN / "pg_ctl"), "-D", str(source / "postgres"), "status"],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        raise ValueError("PostgreSQL is still running from the old folder. Quit Traceback (or run stop) first.")
    for name in ("api", "ui", "processor"):
        if pid_alive(source / f"{name}.pid"):
            raise ValueError(f"The Traceback {name} service is still running; quit Traceback first.")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(STATE))
    STATE.chmod(0o700)
    conf = STATE / "postgres" / "postgresql.conf"
    if conf.exists():
        socket_path = str(STATE).replace("'", "''")
        with conf.open("a") as config:
            # The last setting wins, so this replaces the old in-repo socket directory.
            config.write(f"\nunix_socket_directories = '{socket_path}'  # moved by local_db.py move-data\n")
    print(f"Moved Traceback data to {STATE}. Set {ENV_VAR} in .env to pin this location if you like.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("init", "start", "stop", "status", "create-test-db", "move-data", "where"):
        commands.add_parser(command)
    backup_parser = commands.add_parser("backup")
    backup_parser.add_argument("destination", type=Path)
    restore_parser = commands.add_parser("restore")
    restore_parser.add_argument("source", type=Path)
    restore_parser.add_argument("--database", required=True)
    restore_parser.add_argument("--assets", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "init":
            init()
        elif args.command == "start":
            start()
        elif args.command == "stop":
            run("pg_ctl", "-D", str(DATA), "-m", "fast", "-w", "stop")
        elif args.command == "status":
            run("pg_ctl", "-D", str(DATA), "status")
        elif args.command == "create-test-db":
            if not exists("traceback_test"):
                create("traceback_test")
            print("traceback_test is ready; no existing data was removed.")
        elif args.command == "move-data":
            move_data()
        elif args.command == "where":
            print(STATE)
        elif args.command == "backup":
            backup(args.destination)
        else:
            restore(args.source, args.database, args.assets)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Local database operation failed: {error}\n")


if __name__ == "__main__":
    main()
