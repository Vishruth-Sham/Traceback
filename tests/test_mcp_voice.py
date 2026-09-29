"""MCP parity for voice proposals: typed capture, inspect, correct/retry, accept; and deliberate exclusions."""
import asyncio
import json
import uuid

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from tests.test_mcp_acceptance import live_api, mcp_client  # noqa: F401  (real backend + REST-only adapter client)
from tests.test_mcp_tools_unit import FakeRestClient
from tests.test_voice_api import API, TOKEN, clear_override, now_ist, settings_override, slots, voice  # noqa: F401
from traceback_mcp.runtime import set_client
from traceback_mcp.server import build_server
from traceback_mcp.tools import captures


def tool_names() -> set[str]:
    return {tool.name for tool in asyncio.run(build_server().list_tools())}


# ---- registration and exclusions ------------------------------------------------------------------
def test_voice_parity_tools_are_registered_with_correct_annotations():
    tools = {tool.name: tool for tool in asyncio.run(build_server().list_tools())}
    assert {"accept_capture_proposal", "get_capabilities", "create_capture", "get_capture", "list_captures", "correct_capture", "retry_capture", "apply_capture_interpretation", "archive_capture"} <= set(tools)
    assert tools["get_capabilities"].annotations.read_only_hint is True
    assert tools["accept_capture_proposal"].annotations.destructive_hint is False


def test_processor_only_binary_and_destructive_voice_paths_are_not_exposed():
    names = tool_names()
    forbidden = {
        "claim_capture", "claim_next", "claim_next_capture", "fail_capture", "checkpoint_transcript", "submit_capture_proposal",
        "create_voice_capture", "upload_voice", "upload_asset", "create_asset", "voice_captures", "accept_processor_proposal",
        "storage_summary", "delete_voice_by_command",
    }
    assert not names & forbidden
    schemas = {tool.name: json.dumps(tool.input_schema if hasattr(tool, "input_schema") else tool.inputSchema) for tool in asyncio.run(build_server().list_tools())}
    for name, schema in schemas.items():
        assert "lease_token" not in schema, name  # lease tokens never reach MCP
    accept_schema = schemas["accept_capture_proposal"]
    assert '"mode"' not in accept_schema  # manual mode only; processor-mode accept is not reachable
    assert "bytes" not in json.dumps(schemas["create_capture"]).lower().replace("timestamp", "")


def test_accept_forwards_versions_generation_overrides_and_overdue_confirmation():
    fake = FakeRestClient()
    set_client(fake)
    try:
        capture_id = uuid.uuid4()
        captures.accept_capture_proposal(capture_id=capture_id, expected_version=4, expected_generation=2, overrides={"title": "Edited", "due_date": None}, confirm_overdue=True, idempotency_key="k1")
        name, args, kwargs = fake.calls[-1]
        assert name == "accept_capture_proposal" and args[0] == str(capture_id) and kwargs == {"idempotency_key": "k1"}
        assert args[1] == {"expected_version": 4, "expected_generation": 2, "overrides": {"title": "Edited", "due_date": None}, "confirm_overdue": True}
        captures.accept_capture_proposal(capture_id=capture_id, expected_version=4, expected_generation=2)
        assert fake.calls[-1][1][1] == {"expected_version": 4, "expected_generation": 2}  # nothing extra, no confirm by default
    finally:
        set_client(None)


def test_typed_voice_capture_forwards_profile_and_marks_entry_point_mcp_typed():
    fake = FakeRestClient()
    set_client(fake)
    try:
        captures.create_capture(source_type="typed", raw_text="Remind me to call mom", captured_at=now_ist().isoformat(), source_timezone="Asia/Kolkata",
                                timestamp_origin="client_supplied", processing_profile="voice_command", allowed_intents=["create_task"])
        body = fake.calls[-1][1][0]
        assert body["metadata"] == {"processing_profile": "voice_command", "entry_point": "mcp_typed", "allowed_intents": ["create_task"]}
        with pytest.raises(ToolError) as exc:
            captures.create_capture(source_type="typed", raw_text="x", allowed_intents=["create_task"])
        assert json.loads(str(exc.value))["code"] == "invalid_input"
    finally:
        set_client(None)


def test_correct_capture_accepts_transcript_text_but_still_rejects_unknown_fields():
    fake = FakeRestClient()
    set_client(fake)
    try:
        captures.correct_capture(capture_id=uuid.uuid4(), expected_version=2, corrections={"transcript_text": "fixed"})
        assert fake.calls[-1][1][1] == {"expected_version": 2, "transcript_text": "fixed"}
        with pytest.raises(ToolError):
            captures.correct_capture(capture_id=uuid.uuid4(), expected_version=2, corrections={"lease_token": "x"})
    finally:
        set_client(None)


# ---- end to end over real HTTP -------------------------------------------------------------------
def processor_propose(base_url, capture, slot_values):
    """Stand in for the local processor: claim by id, submit slots (never reachable from MCP)."""
    headers = {"Authorization": f"Bearer {TOKEN}", "X-Traceback-Client": "processor"}
    claim = httpx.post(f"{base_url}{API}/captures/{capture['id']}/claim", json={"expected_generation": capture["processing"]["generation"]}, headers=headers).json()
    response = httpx.post(
        f"{base_url}{API}/captures/{capture['id']}/proposal",
        json={"expected_version": capture["version"], "expected_generation": capture["processing"]["generation"], "lease_token": claim["lease_token"], "slots": slot_values},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_typed_voice_command_round_trip_through_mcp_tools(client, voice, live_api):  # noqa: F811
    base_url, _ = live_api
    caps = captures.get_capabilities()
    assert caps["voice_commands"]["enabled"] is True and caps["voice_commands"]["auto_apply_intents"] == []
    created = captures.create_capture(
        source_type="typed", raw_text="Remind me to renew the passport yesterday", captured_at=now_ist().isoformat(), source_timezone="Asia/Kolkata",
        timestamp_origin="client_supplied", processing_profile="voice_command", idempotency_key=uuid.uuid4().hex,
    )
    assert created["metadata"]["entry_point"] == "mcp_typed" and created["processing"]["state"] == "pending"
    processor_propose(base_url, created, slots(intent="create_task", title="renew the passport", date_phrase="yesterday"))

    reviewed = captures.get_capture(capture_id=created["id"])
    proposal = reviewed["processing"]["proposal"]
    assert reviewed["processing"]["state"] == "awaiting_review" and proposal["disposition"] == "review"
    assert "deadline_past" in proposal["warnings"] and "auto_apply_disabled" in proposal["disposition_reasons"]  # mcp_typed is never auto-applied

    with pytest.raises(ToolError) as refused:
        captures.accept_capture_proposal(capture_id=created["id"], expected_version=reviewed["version"], expected_generation=reviewed["processing"]["generation"])
    payload = json.loads(str(refused.value))
    assert payload["code"] == "overdue_confirmation_required" and payload["details"]["overdue_by_seconds"] > 0

    with pytest.raises(ToolError) as stale:
        captures.accept_capture_proposal(capture_id=created["id"], expected_version=reviewed["version"] - 1, expected_generation=reviewed["processing"]["generation"], confirm_overdue=True)
    stale_payload = json.loads(str(stale.value))
    assert stale_payload["code"] == "version_conflict" and stale_payload["details"]["state"] == "awaiting_review"

    accepted = captures.accept_capture_proposal(
        capture_id=created["id"], expected_version=reviewed["version"], expected_generation=reviewed["processing"]["generation"], confirm_overdue=True,
        overrides={"title": "Renew the passport (edited)"},
    )
    assert accepted["capture"]["processing"]["state"] == "resolved" and accepted["items"][0]["title"] == "Renew the passport (edited)"


def test_disabled_voice_is_surfaced_and_manual_mcp_paths_still_work(client, voice, live_api):  # noqa: F811
    base_url, _ = live_api
    created = captures.create_capture(source_type="typed", raw_text="Add a note called Kept", captured_at=now_ist().isoformat(), source_timezone="Asia/Kolkata",
                                      timestamp_origin="client_supplied", processing_profile="voice_command")
    clear_override()
    settings_override(voice_commands_enabled=False)
    with pytest.raises(ToolError) as exc:
        captures.create_capture(source_type="typed", raw_text="x", captured_at=now_ist().isoformat(), source_timezone="Asia/Kolkata",
                                timestamp_origin="client_supplied", processing_profile="voice_command")
    assert json.loads(str(exc.value))["code"] == "capability_disabled"
    assert captures.get_capabilities()["voice_commands"]["enabled"] is False
    with pytest.raises(ToolError) as corrected:
        captures.correct_capture(capture_id=created["id"], expected_version=created["version"], corrections={"transcript_text": "changed"})
    assert json.loads(str(corrected.value))["code"] == "capability_disabled"
    resolved = captures.apply_capture_interpretation(
        capture_id=created["id"], expected_version=created["version"], expected_generation=created["processing"]["generation"],
        items=[{"kind": "create", "item": {"item_type": "note", "title": "Kept", "content_md": "typed by hand"}}],
    )
    assert resolved["capture"]["processing"]["state"] == "resolved"
    assert base_url
