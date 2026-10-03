"""The daily-log MCP tools: argument shaping against a fake client, and one pass through the real backend."""

from datetime import date

import pytest

from mcp.server.mcpserver.exceptions import ToolError

from traceback_mcp.runtime import set_client
from traceback_mcp.tools import log


class Recorder:
    def __init__(self):
        self.calls = []

    def create_log_entry(self, body):
        self.calls.append(("create", body))
        return {"ok": True}

    def get_log_day(self, day):
        self.calls.append(("day", day))
        return {"ok": True}

    categories = [{"id": "c1", "name": "food", "description": "Meals"}]

    def list_log_categories(self):
        return list(self.categories)

    def create_log_category(self, body):
        self.calls.append(("create_category", body))
        return {"id": "new", **body}

    def update_log_category(self, category_id, body):
        self.calls.append(("update_category", category_id, body))
        return {"id": category_id, **body}

    def delete_log_category(self, category_id):
        self.calls.append(("delete_category", category_id))

    def classify_log(self, body):
        self.calls.append(("classify", body))
        return {"ok": True}

    def get_log_range(self, **params):
        self.calls.append(("range", params))
        return {"ok": True}

    def search_log(self, **params):
        self.calls.append(("search", params))
        return {"ok": True}


@pytest.fixture
def recorder():
    fake = Recorder()
    set_client(fake)
    yield fake
    set_client(None)


def test_log_entry_sends_only_what_was_given(recorder):
    log.log_entry("lunch with Priya")
    log.log_entry("gym", at="2026-10-03T15:40:00+05:30")
    assert recorder.calls == [
        ("create", {"text": "lunch with Priya"}),
        ("create", {"text": "gym", "at": "2026-10-03T15:40:00+05:30"}),
    ]


def test_get_day_log_passes_iso_date_or_none(recorder):
    log.get_day_log()
    log.get_day_log(date(2026, 10, 2))
    assert recorder.calls == [("day", None), ("day", "2026-10-02")]


def test_get_log_range_passes_iso_dates(recorder):
    log.get_log_range(date(2026, 9, 1), date(2026, 9, 30))
    assert recorder.calls == [("range", {"start": "2026-09-01", "end": "2026-09-30"})]


def test_search_log_bounds_the_limit(recorder):
    log.search_log("udupi", limit=10_000)
    assert recorder.calls[0][1]["q"] == "udupi"
    assert recorder.calls[0][1]["limit"] <= 250


def test_classify_log_defaults_to_today_and_ignores_date_for_all_days(recorder):
    log.classify_log()
    log.classify_log(date(2026, 10, 2))
    log.classify_log(date(2026, 10, 2), all_days=True)
    assert recorder.calls == [
        ("classify", {"all_days": False}),
        ("classify", {"all_days": False, "date": "2026-10-02"}),
        ("classify", {"all_days": True}),
    ]


def test_list_categories_returns_what_the_client_returns(recorder):
    assert log.list_log_categories() == recorder.categories


def test_save_creates_a_missing_category_and_normalises_the_lookup(recorder):
    log.save_log_category("Caffeine", "Coffee, tea")
    log.save_log_category(" FOOD ", description="Meals and snacks")
    assert recorder.calls == [
        ("create_category", {"name": "Caffeine", "description": "Coffee, tea"}),
        ("update_category", "c1", {"description": "Meals and snacks"}),
    ]


def test_save_can_rename_and_does_nothing_when_nothing_changes(recorder):
    log.save_log_category("food", rename_to="meals")
    assert log.save_log_category("food") == recorder.categories[0]
    assert recorder.calls == [("update_category", "c1", {"name": "meals"})]


def test_rename_or_delete_of_an_unknown_category_is_a_not_found_error(recorder):
    with pytest.raises(ToolError, match="not_found"):
        log.save_log_category("nope", rename_to="x")
    with pytest.raises(ToolError, match="not_found"):
        log.delete_log_category("nope")
    assert recorder.calls == []


def test_delete_finds_the_category_by_name(recorder):
    assert log.delete_log_category("Food") == {"deleted": "food"}
    assert recorder.calls == [("delete_category", "c1")]


def test_tools_are_registered_with_the_right_annotations():
    from traceback_mcp.server import _TOOLS

    registered = {fn.__name__: annotations for fn, _title, annotations in _TOOLS}
    assert registered["log_entry"].read_only_hint is False
    assert registered["log_entry"].destructive_hint is False
    assert registered["get_day_log"].read_only_hint is True
    assert registered["search_log"].read_only_hint is True
    assert registered["get_log_range"].read_only_hint is True
    assert registered["classify_log"].read_only_hint is False
    assert registered["classify_log"].destructive_hint is False
    assert registered["list_log_categories"].read_only_hint is True
    assert registered["save_log_category"].read_only_hint is False
    assert registered["delete_log_category"].read_only_hint is False
