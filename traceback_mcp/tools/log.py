"""Daily log tools: append a free-text entry, read a day, search, classify.

`log_entry` writes immediately with no review step. Entries are never edited; classification (labels and
summaries) is produced by the local model, either from the UI or by `classify_log`.
"""

from datetime import date as Date

import json

from mcp.server.mcpserver.exceptions import ToolError

from traceback_mcp.errors import guarded
from traceback_mcp.runtime import get_client
from traceback_mcp.tools.common import bounded_limit


@guarded
def log_entry(text: str, at: str | None = None) -> dict:
    """Add one free-text line to the daily log, exactly as written. Applied immediately; no confirmation.

    `at` is an optional ISO 8601 time for when it happened (a time without an offset is read in the user's
    timezone); omit it to use now. Times before the day-start hour (default 04:00) belong to the previous day;
    the response's `log_date` shows which day it landed on.
    """
    body: dict = {"text": text}
    if at is not None:
        body["at"] = at
    return get_client().create_log_entry(body)


@guarded
def get_day_log(date: Date | None = None) -> dict:
    """Read one day of the log: entries in time order, their labels, and the day summary if it was generated.

    Omit `date` (YYYY-MM-DD) for today's logical day.
    """
    return get_client().get_log_day(date.isoformat() if date is not None else None)


@guarded
def get_log_range(start: Date, end: Date) -> dict:
    """Read every day that has entries from `start` to `end` inclusive, oldest first, in one call (max 93 days).

    Each day has its entries (time, text, labels) and its summary if one was generated. Days with no entries are
    omitted. Built for weekly or monthly review: days that were never classified have no labels or summary, so run
    `classify_log` with `all_days=true` first if the labels matter.
    """
    return get_client().get_log_range(start=start.isoformat(), end=end.isoformat())


@guarded
def search_log(query: str, limit: int = 25) -> dict:
    """Case-insensitive text search across all log entries, newest first."""
    return get_client().search_log(q=query, limit=bounded_limit(limit))


@guarded
def classify_log(date: Date | None = None, all_days: bool = False) -> dict:
    """Run the local model over a day's entries to rebuild its labels and summary. Entries are never changed.

    Omit `date` for today's logical day, or set `all_days=true` to redo every day (slow). Safe to repeat: it
    replaces the previous labels and summary. Fails if the local model (Ollama) is not running.
    """
    body: dict = {"all_days": all_days}
    if date is not None and not all_days:
        body["date"] = date.isoformat()
    return get_client().classify_log(body)


def _find_category(categories: list[dict], name: str) -> dict | None:
    wanted = name.strip().lower()
    return next((category for category in categories if category["name"] == wanted), None)


def _not_found(name: str) -> ToolError:
    return ToolError(json.dumps({"error": {"code": "not_found", "message": f"No log category named {name.strip().lower()!r}"}}))


@guarded
def list_log_categories() -> list[dict]:
    """List the log categories the local model may apply: each has a `name` and the one-line `description` it reads."""
    return get_client().list_log_categories()


@guarded
def save_log_category(name: str, description: str | None = None, rename_to: str | None = None) -> dict:
    """Create a log category, or update the one with this name. Applied immediately; no confirmation.

    Names are lowercase. If `name` exists, `description` and/or `rename_to` change it; otherwise a new category is
    created (`rename_to` is then an error). Existing labels are not rewritten: run `classify_log` to rebuild them.
    """
    client = get_client()
    existing = _find_category(client.list_log_categories(), name)
    if existing is None:
        if rename_to is not None:
            raise _not_found(name)
        return client.create_log_category({"name": name, "description": description or ""})
    patch = {key: value for key, value in (("description", description), ("name", rename_to)) if value is not None}
    return client.update_log_category(existing["id"], patch) if patch else existing


@guarded
def delete_log_category(name: str) -> dict:
    """Remove a log category by name. Applied immediately; no confirmation.

    Entries are never touched, but labels already stored with this name stay on old entries until `classify_log`
    is re-run.
    """
    client = get_client()
    existing = _find_category(client.list_log_categories(), name)
    if existing is None:
        raise _not_found(name)
    client.delete_log_category(existing["id"])
    return {"deleted": existing["name"]}
