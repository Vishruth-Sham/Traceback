"""Real HTTP-to-PostgreSQL acceptance tests for the MCP adapter.

Runs the actual FastAPI app under a real uvicorn server bound to a real
loopback TCP port, backed by the same disposable PostgreSQL database the
`client` fixture (tests/conftest.py) creates and drops. `traceback_mcp`
tool functions then talk to it exactly as the stdio adapter would: real
HTTP requests, a real bearer token, real REST-side validation, versions,
and error envelopes. No database import, and no direct PostgreSQL
connection, happens from traceback_mcp itself anywhere in this file.
"""

import os
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from traceback_mcp.config import McpSettings
from traceback_mcp.rest_client import RestClient
from traceback_mcp.runtime import set_client
from traceback_mcp.tools import assets, captures, items, relations, sources, tasks


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def live_api(client):  # noqa: ARG001 - depends on the session-scoped real-Postgres fixture for its side effects
    from backend.main import app

    port = _free_loopback_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:
        pytest.fail("uvicorn did not start in time")

    base_url = f"http://127.0.0.1:{port}"
    token = os.environ["TRACEBACK_API_TOKEN"]
    try:
        yield base_url, token
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.fixture(autouse=True)
def mcp_client(live_api):
    base_url, token = live_api
    settings = McpSettings(api_base_url=base_url, api_token=token, client_label="mcp-acceptance-test")
    rc = RestClient(settings)
    set_client(rc)
    yield rc
    set_client(None)


def test_list_categories_over_real_http(live_api):
    categories = items.list_categories()
    assert [c["slug"] for c in categories] == ["health-food", "personal-growth", "books", "learning", "projects", "other"]


def test_full_item_and_task_lifecycle_over_real_http(live_api):
    created = items.create_item(item_type="task", title="MCP acceptance task", due_date="2026-12-01")
    assert created["placement_state"] == "inbox"
    assert created["due_date"] == "2026-12-01"

    fetched = items.get_item(item_id=created["id"])
    assert fetched["id"] == created["id"]

    updated = items.update_item(item_id=created["id"], expected_version=fetched["version"], patch={"title": "Renamed task"})
    assert updated["title"] == "Renamed task"
    assert updated["version"] == fetched["version"] + 1

    completed = tasks.complete_task(item_id=created["id"], expected_version=updated["version"])
    assert completed["status"] == "completed"

    reopened = tasks.reopen_task(item_id=created["id"], expected_version=completed["version"])
    assert reopened["status"] == "open"

    archived = items.archive_item(item_id=created["id"], expected_version=reopened["version"])
    assert archived["archived_at"] is not None

    restored = items.restore_item(item_id=created["id"], expected_version=archived["version"])
    assert restored["archived_at"] is None


def test_version_conflict_surfaces_as_structured_tool_error(live_api):
    from mcp.server.mcpserver.exceptions import ToolError
    import json

    created = items.create_item(item_type="note", title="Conflict target")
    with pytest.raises(ToolError) as exc:
        items.update_item(item_id=created["id"], expected_version=created["version"] + 5, patch={"title": "stale write"})
    payload = json.loads(str(exc.value))
    assert payload["code"] == "version_conflict"


def test_not_found_surfaces_as_structured_tool_error():
    from mcp.server.mcpserver.exceptions import ToolError
    import json
    import uuid

    with pytest.raises(ToolError) as exc:
        items.get_item(item_id=str(uuid.uuid4()))
    payload = json.loads(str(exc.value))
    assert payload["code"] == "not_found"


def test_move_link_and_relation_lifecycle(live_api):
    project = items.create_item(item_type="project", title="MCP acceptance project")
    task = items.create_item(item_type="task", title="Task under project")
    moved = items.move_item(item_id=task["id"], expected_version=task["version"], project_id=project["id"], project_expected_version=project["version"])
    assert any(r["relation"] == "part_of" and r["to_item_id"] == project["id"] for r in moved["relations"])

    note = items.create_item(item_type="note", title="Related note")
    linked = relations.link_items(
        from_item_id=note["id"], from_expected_version=note["version"], relation="related_to", to_item_id=project["id"], to_expected_version=moved["version"]
    )
    unlinked = relations.unlink_items(relation_id=linked["id"], from_expected_version=note["version"] + 1, to_expected_version=moved["version"] + 1)
    assert unlinked["deleted_relation_id"] == linked["id"]


def test_capture_manual_interpretation_and_provenance(live_api):
    capture = captures.create_capture(source_type="typed", raw_text="Buy milk tomorrow", timestamp_origin="unknown")
    assert capture["processing"]["state"] == "pending"

    interpreted = captures.apply_capture_interpretation(
        capture_id=capture["id"],
        expected_version=capture["version"],
        expected_generation=capture["processing"]["generation"],
        items=[{"kind": "create", "item": {"item_type": "task", "title": "Buy milk"}}],
    )
    assert interpreted["capture"]["processing"]["state"] == "resolved"
    item_id = interpreted["items"][0]["id"]

    source_list = sources.get_item_sources(item_id=item_id)
    assert any(s["capture_id"] == capture["id"] for s in source_list)

    fetched_capture = captures.get_capture(capture_id=capture["id"])
    assert item_id in fetched_capture["resulting_item_ids"]


def test_capture_archive_requires_unlinking_before_permanent_delete(live_api):
    capture = captures.create_capture(source_type="typed", raw_text="Standalone capture")
    archived = captures.archive_capture(capture_id=capture["id"], expected_version=capture["version"])

    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError):
        # confirm defaults to False: must be rejected before any REST call.
        captures.delete_capture_permanently(capture_id=capture["id"], expected_version=archived["version"], confirm=False)

    result = captures.delete_capture_permanently(capture_id=capture["id"], expected_version=archived["version"], confirm=True)
    assert result["deleted_capture_id"] == capture["id"]


def test_permanent_item_delete_requires_archive_first(live_api):
    note = items.create_item(item_type="note", title="Delete me")
    import json

    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError) as exc:
        items.delete_item_permanently(item_id=note["id"], expected_version=note["version"], confirm=True)
    payload = json.loads(str(exc.value))
    assert payload["code"] in {"invalid_transition", "not_found"} or "archiv" in payload["message"].lower()

    archived = items.archive_item(item_id=note["id"], expected_version=note["version"])
    deleted = items.delete_item_permanently(item_id=note["id"], expected_version=archived["version"], confirm=True)
    assert deleted["deleted_item_id"] == note["id"]


def test_folder_creation_nesting_and_move_over_real_http(live_api):
    parent = items.create_item(item_type="folder", title="Learning root")
    child_folder = items.create_item(item_type="folder", title="Distributed systems")
    note = items.create_item(item_type="note", title="Raft summary")

    linked = relations.link_items(
        from_item_id=child_folder["id"], from_expected_version=child_folder["version"], relation="part_of", to_item_id=parent["id"], to_expected_version=parent["version"]
    )
    assert linked["relation"] == "part_of"

    refreshed_child = items.get_item(item_id=child_folder["id"])
    moved_note = items.move_item(
        item_id=note["id"], expected_version=note["version"], folder_id=refreshed_child["id"], folder_expected_version=refreshed_child["version"]
    )
    assert any(r["relation"] == "part_of" and r["to_item_id"] == refreshed_child["id"] for r in moved_note["relations"])

    children = items.list_items(parent_id=refreshed_child["id"])
    assert [i["id"] for i in children["items"]] == [note["id"]]

    import json

    from mcp.server.mcpserver.exceptions import ToolError

    refreshed_parent = items.get_item(item_id=parent["id"])
    with pytest.raises(ToolError) as exc:
        relations.link_items(
            from_item_id=refreshed_parent["id"],
            from_expected_version=refreshed_parent["version"],
            relation="part_of",
            to_item_id=refreshed_child["id"],
            to_expected_version=items.get_item(item_id=refreshed_child["id"])["version"],
        )
    payload = json.loads(str(exc.value)[str(exc.value).index("{"):])
    assert payload["code"] == "invalid_input"


def test_asset_link_archive_restore_and_permanent_delete_lifecycle(live_api):
    # Asset bytes upload stays REST-only (not an MCP tool); use real HTTP directly,
    # exactly like a developer would, to get an asset ID the MCP asset tools can act on.
    base_url, token = live_api
    uploaded = httpx.post(
        f"{base_url}/api/v1/assets",
        params={"filename": "acceptance-note.txt"},
        content=b"asset bytes for MCP acceptance",
        headers={"Content-Type": "text/plain", "Authorization": f"Bearer {token}"},
    )
    assert uploaded.status_code == 201, uploaded.text
    asset_id = uploaded.json()["id"]

    fetched = assets.get_asset(asset_id=asset_id)
    assert fetched["id"] == asset_id

    note = items.create_item(item_type="note", title="Note with an asset")
    linked = assets.link_item_asset(item_id=note["id"], asset_id=asset_id, expected_version=note["version"])
    assert linked["version"] == note["version"] + 1

    from mcp.server.mcpserver.exceptions import ToolError
    import json

    # Still linked: permanent delete must fail even with confirm=true, and refuse
    # entirely without confirm=true before any HTTP call is made.
    with pytest.raises(ToolError):
        assets.delete_asset_permanently(asset_id=asset_id, expected_version=fetched["version"], confirm=False)

    unlinked = assets.unlink_item_asset(item_id=note["id"], asset_id=asset_id, expected_version=linked["version"])
    assert unlinked["version"] == linked["version"] + 1

    with pytest.raises(ToolError) as exc:
        assets.delete_asset_permanently(asset_id=asset_id, expected_version=fetched["version"], confirm=True)
    payload = json.loads(str(exc.value))
    assert payload["code"] == "invalid_transition"  # not yet archived

    archived = assets.archive_asset(asset_id=asset_id, expected_version=fetched["version"])
    assert archived["archived_at"] is not None

    restored = assets.restore_asset(asset_id=asset_id, expected_version=archived["version"])
    assert restored["archived_at"] is None

    rearchived = assets.archive_asset(asset_id=asset_id, expected_version=restored["version"])
    deleted = assets.delete_asset_permanently(asset_id=asset_id, expected_version=rearchived["version"], confirm=True)
    assert deleted["state"] == "deleted"

    with pytest.raises(ToolError) as exc:
        assets.get_asset(asset_id=asset_id)
    assert json.loads(str(exc.value))["code"] == "not_found"


def test_item_source_link_and_unlink_lifecycle(live_api):
    note = items.create_item(item_type="note", title="Sourced note")
    capture = captures.create_capture(source_type="typed", raw_text="Original capture text")

    assert sources.get_item_sources(item_id=note["id"]) == []

    linked = sources.link_item_source(
        item_id=note["id"],
        capture_id=capture["id"],
        item_expected_version=note["version"],
        capture_expected_version=capture["version"],
    )
    assert linked["capture_id"] == capture["id"]

    source_list = sources.get_item_sources(item_id=note["id"])
    assert [s["id"] for s in source_list] == [linked["id"]]

    unlinked = sources.unlink_item_source(
        item_id=note["id"],
        source_id=linked["id"],
        item_expected_version=note["version"] + 1,
        capture_expected_version=capture["version"] + 1,
    )
    assert unlinked["deleted_source_id"] == linked["id"]
    assert sources.get_item_sources(item_id=note["id"]) == []


def test_backend_unavailable_error_is_distinct_from_domain_errors():
    from mcp.server.mcpserver.exceptions import ToolError
    import json

    unreachable = McpSettings(api_base_url="http://127.0.0.1:1", api_token="x" * 24, request_timeout_s=1.0)
    set_client(RestClient(unreachable))
    try:
        with pytest.raises(ToolError) as exc:
            items.list_categories()
        payload = json.loads(str(exc.value))
        assert payload["code"] == "backend_unavailable"
    finally:
        set_client(None)
