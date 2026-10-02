"""The MCP catalog leaves voice-command processing to the UI and backend."""

import asyncio
import json
import uuid

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from tests.test_mcp_tools_unit import FakeRestClient
from traceback_mcp.runtime import set_client
from traceback_mcp.server import build_server
from traceback_mcp.tools import captures


def test_voice_command_tools_and_profile_are_not_discoverable():
    tools = {tool.name: tool for tool in asyncio.run(build_server().list_tools())}
    assert "accept_capture_proposal" not in tools
    assert "get_capabilities" not in tools
    assert {"create_capture", "get_capture", "apply_capture_interpretation"} <= tools.keys()

    capture_schema = json.dumps(tools["create_capture"].input_schema)
    assert "voice_command" not in capture_schema
    assert "allowed_intents" not in capture_schema


def test_voice_only_arguments_are_rejected_before_rest_call():
    fake = FakeRestClient()
    set_client(fake)
    try:
        with pytest.raises(ToolError) as profile_error:
            captures.create_capture(source_type="typed", raw_text="hello", processing_profile="voice_command")
        assert json.loads(str(profile_error.value))["code"] == "invalid_input"

        with pytest.raises(ToolError) as correction_error:
            captures.correct_capture(
                capture_id=uuid.uuid4(), expected_version=1, corrections={"transcript_text": "changed"}
            )
        assert json.loads(str(correction_error.value))["code"] == "invalid_input"
        assert fake.calls == []
    finally:
        set_client(None)
