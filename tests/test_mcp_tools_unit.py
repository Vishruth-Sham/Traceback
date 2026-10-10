"""Unit tests for traceback_mcp tool functions against a fake REST client.

No network, no PostgreSQL: these verify argument shaping (tri-state PATCH
semantics, unknown-field rejection, destructive confirm gating, error
mapping) in isolation. See test_mcp_protocol.py and test_mcp_acceptance.py
for tests that exercise real MCP framing and a real backend.
"""

import json
import uuid

import pytest

from mcp.server.mcpserver.exceptions import ToolError

from traceback_mcp.rest_client import BackendUnavailableError, RestError
from traceback_mcp.runtime import set_client
from traceback_mcp.tools import assets, captures, items, relations, sources, tasks


class FakeRestClient:
    def __init__(self):
        self.calls: list[tuple[str, tuple, dict]] = []

    def _record(self, name, args, kwargs, result=None):
        self.calls.append((name, args, kwargs))
        return result

    def __getattr__(self, name):
        def method(*args, **kwargs):
            return self._record(name, args, kwargs, result={"ok": True, "method": name, "args": args, "kwargs": kwargs})

        return method


@pytest.fixture(autouse=True)
def fake_client():
    fake = FakeRestClient()
    set_client(fake)
    yield fake
    set_client(None)


def last_call(fake):
    return fake.calls[-1]


# --- create/update tri-state semantics -------------------------------------------------


def test_create_item_only_includes_supplied_optional_fields(fake_client):
    items.create_item(item_type="note", title="Hello", inbox=True)
    name, args, kwargs = last_call(fake_client)
    body = args[0]
    assert name == "create_item"
    assert body == {"item_type": "note", "title": "Hello", "content_md": ""}


def test_create_item_includes_deadline_fields_when_supplied(fake_client):
    items.create_item(item_type="task", title="Ship it", due_date="2026-10-01", due_time="15:00:00", due_timezone="Asia/Kolkata")
    _, args, _ = last_call(fake_client)
    assert args[0]["due_date"] == "2026-10-01"
    assert args[0]["due_time"] == "15:00:00"
    assert args[0]["due_timezone"] == "Asia/Kolkata"


def test_create_item_can_include_atomic_folder_destination(fake_client):
    folder_id = uuid.uuid4()
    items.create_item(item_type="note", title="Nested", folder_id=folder_id, folder_expected_version=4)
    _, args, _ = last_call(fake_client)
    assert args[0]["folder_id"] == str(folder_id)
    assert args[0]["folder_expected_version"] == 4


def test_update_item_omitted_field_is_absent_from_body(fake_client):
    items.update_item(item_id="i1", expected_version=3, patch={"title": "New title"})
    name, args, kwargs = last_call(fake_client)
    assert name == "update_item"
    assert args[0] == "i1"
    assert args[1] == {"expected_version": 3, "title": "New title"}
    assert "content_md" not in args[1]


def test_update_item_explicit_null_clears_field(fake_client):
    items.update_item(item_id="i1", expected_version=3, patch={"due_date": None, "due_time": None, "due_timezone": None})
    _, args, _ = last_call(fake_client)
    body = args[1]
    assert body["due_date"] is None and body["due_time"] is None and body["due_timezone"] is None


def test_update_item_rejects_unknown_patch_field(fake_client):
    with pytest.raises(ToolError) as exc:
        items.update_item(item_id="i1", expected_version=1, patch={"item_type": "task"})
    payload = json.loads(str(exc.value))
    assert payload["code"] == "invalid_input"
    assert not fake_client.calls  # never reached the REST client


def test_correct_capture_rejects_unknown_field(fake_client):
    with pytest.raises(ToolError) as exc:
        captures.correct_capture(capture_id="c1", expected_version=1, corrections={"raw_text": "nope"})
    payload = json.loads(str(exc.value))
    assert payload["code"] == "invalid_input"
    assert not fake_client.calls


def test_correct_capture_forwards_only_supplied_fields(fake_client):
    captures.correct_capture(capture_id="c1", expected_version=2, corrections={"description": "fixed"})
    name, args, _ = last_call(fake_client)
    assert name == "correct_capture"
    assert args[1] == {"expected_version": 2, "description": "fixed"}


# --- destructive confirm gating ----------------------------------------------------------


def test_delete_item_permanently_requires_confirm(fake_client):
    with pytest.raises(ToolError) as exc:
        items.delete_item_permanently(item_id="i1", expected_version=1, confirm=False)
    payload = json.loads(str(exc.value))
    assert payload["code"] == "confirmation_required"
    assert not fake_client.calls


def test_delete_item_permanently_calls_rest_when_confirmed(fake_client):
    items.delete_item_permanently(item_id="i1", expected_version=1, confirm=True)
    name, args, kwargs = last_call(fake_client)
    assert name == "delete_item"
    assert kwargs["confirm"] is True
    assert kwargs["expected_version"] == 1


def test_delete_capture_permanently_requires_confirm(fake_client):
    with pytest.raises(ToolError):
        captures.delete_capture_permanently(capture_id="c1", expected_version=1, confirm=False)
    assert not fake_client.calls


def test_delete_asset_permanently_requires_confirm(fake_client):
    with pytest.raises(ToolError):
        assets.delete_asset_permanently(asset_id="a1", expected_version=1, confirm=False)
    assert not fake_client.calls


# --- error mapping -------------------------------------------------------------------------


def test_rest_error_becomes_structured_tool_error(fake_client):
    def raise_conflict(*a, **k):
        raise RestError(409, "version_conflict", "The item changed since it was read", {"id": "i1", "expected_version": 1, "actual_version": 2})

    fake_client.get_item = raise_conflict
    with pytest.raises(ToolError) as exc:
        items.get_item(item_id="i1")
    payload = json.loads(str(exc.value))
    assert payload == {
        "code": "version_conflict",
        "message": "The item changed since it was read",
        "details": {"id": "i1", "expected_version": 1, "actual_version": 2},
    }


def test_backend_unavailable_becomes_structured_tool_error(fake_client):
    def raise_unavailable(*a, **k):
        raise BackendUnavailableError("could not reach the Traceback API at http://127.0.0.1:8000: refused")

    fake_client.list_categories = raise_unavailable
    with pytest.raises(ToolError) as exc:
        items.list_categories()
    payload = json.loads(str(exc.value))
    assert payload["code"] == "backend_unavailable"


# --- other tool shaping -----------------------------------------------------------------------


def test_move_item_builds_project_destination(fake_client):
    items.move_item(item_id="i1", expected_version=1, project_id="p1", project_expected_version=4)
    _, args, _ = last_call(fake_client)
    assert args[1] == {"expected_version": 1, "inbox": False, "project_id": "p1", "project_expected_version": 4}


def test_apply_capture_interpretation_forces_manual_mode(fake_client):
    captures.apply_capture_interpretation(
        capture_id="c1",
        expected_version=1,
        expected_generation=1,
        items=[{"kind": "create", "item": {"item_type": "note", "title": "x"}}],
    )
    name, args, _ = last_call(fake_client)
    assert name == "apply_capture_interpretation"
    assert args[1]["mode"] == "manual"
    assert "lease_token" not in args[1]


def test_link_items_and_unlink_items(fake_client):
    relations.link_items(from_item_id="a", from_expected_version=1, relation="related_to", to_item_id="b", to_expected_version=1)
    assert last_call(fake_client)[0] == "create_relation"
    relations.unlink_items(relation_id="r1", from_expected_version=2, to_expected_version=2)
    assert last_call(fake_client)[0] == "delete_relation"


def test_task_lifecycle_tools(fake_client):
    tasks.list_tasks()
    assert last_call(fake_client)[0] == "list_tasks"
    tasks.complete_task(item_id="t1", expected_version=1)
    assert last_call(fake_client)[0] == "complete_task"
    tasks.reopen_task(item_id="t1", expected_version=2)
    assert last_call(fake_client)[0] == "reopen_task"


def test_source_link_tools(fake_client):
    sources.link_item_source(item_id="i1", capture_id="c1", item_expected_version=1, capture_expected_version=1)
    assert last_call(fake_client)[0] == "link_item_source"
    sources.unlink_item_source(item_id="i1", source_id="s1", item_expected_version=2, capture_expected_version=2)
    assert last_call(fake_client)[0] == "unlink_item_source"


def test_asset_tools_never_expose_content(fake_client):
    assets.get_asset(asset_id="a1")
    assert last_call(fake_client)[0] == "get_asset"
    assert not hasattr(assets, "get_asset_content")
    assert not hasattr(assets, "upload_asset")


# --- create_capture metadata and undo_action idempotency -------------------------------


def test_create_capture_omits_metadata_when_nothing_supplied(fake_client):
    captures.create_capture(source_type="typed", raw_text="hello")
    _, args, _ = last_call(fake_client)
    assert "metadata" not in args[0]


def test_create_capture_includes_only_supplied_metadata_fields(fake_client):
    captures.create_capture(
        source_type="typed",
        raw_text="hello",
        client_app="voice-memo",
        supplied_title="A title",
        contextual_item_id="11111111-1111-1111-1111-111111111111",
    )
    _, args, _ = last_call(fake_client)
    assert args[0]["metadata"] == {
        "client_app": "voice-memo",
        "supplied_title": "A title",
        "contextual_item_id": "11111111-1111-1111-1111-111111111111",
    }


def test_undo_action_accepts_idempotency_key_and_stringifies_version_keys(fake_client):
    items.undo_action(action_id="a1", expected_versions={"11111111-1111-1111-1111-111111111111": 2}, idempotency_key="key-1")
    name, args, kwargs = last_call(fake_client)
    assert name == "undo_action"
    assert args[1] == {"expected_versions": {"11111111-1111-1111-1111-111111111111": 2}}
    assert kwargs.get("idempotency_key") == "key-1"


# --- folders (item_type="folder", move_item's folder_id destination) -------------------


def test_create_item_accepts_folder_type(fake_client):
    items.create_item(item_type="folder", title="Distributed systems", inbox=True)
    _, args, _ = last_call(fake_client)
    assert args[0]["item_type"] == "folder"


def test_move_item_builds_folder_destination(fake_client):
    items.move_item(item_id="i1", expected_version=1, folder_id="f1", folder_expected_version=3)
    _, args, _ = last_call(fake_client)
    assert args[1] == {"expected_version": 1, "inbox": False, "folder_id": "f1", "folder_expected_version": 3}


def test_list_items_forwards_parent_id_and_top_level(fake_client):
    items.list_items(parent_id="f1", top_level=True)
    _, _, kwargs = last_call(fake_client)
    assert kwargs["parent_id"] == "f1"
    assert kwargs["top_level"] is True
