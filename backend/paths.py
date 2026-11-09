"""Where Traceback keeps personal data: the PostgreSQL cluster, note assets, credentials and logs.

The data folder lives outside the repository so notes can never be committed by accident.
Set TRACEBACK_DATA_DIR (in the environment or the root .env) to choose it; otherwise a
per-user default is used. This module is stdlib-only so the setup scripts can import it
before the virtualenv exists.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ENV_VAR = "TRACEBACK_DATA_DIR"
ROOT = Path(__file__).resolve().parents[1]
# Where data lived before it moved out of the checkout. Only read by the migration helpers.
LEGACY_DATA_DIR = ROOT / ".local" / "traceback"


def default_data_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Traceback"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "traceback"


def _env_file_value(env_file: Path = ROOT / ".env") -> str | None:
    try:
        lines = env_file.read_text().splitlines()
    except OSError:
        return None
    for line in lines:
        key, sep, value = line.strip().partition("=")
        if sep and key.strip() == ENV_VAR:
            return value.strip().strip("'\"") or None
    return None


def resolve_data_dir(value: str | os.PathLike[str] | None) -> Path:
    """Expand a configured value, refusing locations inside the repository."""
    path = Path(value).expanduser() if value else default_data_dir()
    if not path.is_absolute():
        raise ValueError(f"{ENV_VAR} must be an absolute path (got {value!s}).")
    path = path.resolve()
    if path == ROOT or ROOT in path.parents:
        raise ValueError(f"{ENV_VAR} must be outside the Traceback checkout ({ROOT}) so notes are never committed.")
    return path


def data_dir() -> Path:
    return resolve_data_dir(os.environ.get(ENV_VAR) or _env_file_value())


def legacy_data_present() -> bool:
    return (LEGACY_DATA_DIR / "postgres" / "PG_VERSION").exists() or (LEGACY_DATA_DIR / "assets").is_dir()


def require_no_legacy_data(target: Path) -> None:
    """Stop before creating an empty store while the real notes are still in the old in-repo folder."""
    if legacy_data_present() and not target.exists():
        raise ValueError(
            f"Your notes are still in {LEGACY_DATA_DIR}. Stop Traceback, then run "
            f"`python3 scripts/local_db.py move-data` to move them to {target}."
        )
