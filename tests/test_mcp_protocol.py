"""Subprocess MCP protocol integration test.

Launches `python -m traceback_mcp` as a real stdio child process and talks
to it with the official MCP client SDK, so this exercises actual JSON-RPC
initialize/list_tools/call_tool framing, not just direct Python calls. It
still needs a real backend (see the `live_api` fixture in
test_mcp_acceptance.py) because the adapter only ever does real HTTP.
"""

import asyncio
import os
import sys

import pytest

from mcp import ClientSession, StdioServerParameters, stdio_client

from tests.test_mcp_acceptance import live_api  # noqa: F401  (reuse the real backend fixture)


async def _run_protocol_check(base_url: str, token: str) -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "traceback_mcp"],
        env={
            **os.environ,
            "TRACEBACK_MCP_API_BASE_URL": base_url,
            "TRACEBACK_API_TOKEN": token,
            "TRACEBACK_MCP_CLIENT_LABEL": "mcp-protocol-test",
        },
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init_result = await session.initialize()
            assert init_result.server_info.name == "traceback"

            tools = (await session.list_tools()).tools
            names = {tool.name for tool in tools}
            assert {"list_categories", "create_item", "delete_item_permanently", "get_asset"} <= names

            delete_tool = next(t for t in tools if t.name == "delete_item_permanently")
            assert delete_tool.annotations is not None
            assert delete_tool.annotations.destructive_hint is True
            read_tool = next(t for t in tools if t.name == "list_categories")
            assert read_tool.annotations.read_only_hint is True
            assert read_tool.annotations.open_world_hint is False

            categories_result = await session.call_tool("list_categories", {})
            assert categories_result.is_error is not True
            assert len(categories_result.content) >= 1

            created = await session.call_tool("create_item", {"item_type": "note", "title": "protocol test note"})
            assert created.is_error is not True

            # Destructive call without confirm=true must fail as a structured tool error,
            # not silently perform any deletion or crash the server.
            import json

            import re

            match = re.search(r'"id":\s*"([0-9a-fA-F-]{36})"', created.content[0].text)
            item_id = match.group(1)
            version_match = re.search(r'"version":\s*(\d+)', created.content[0].text)
            version = int(version_match.group(1))

            refused = await session.call_tool(
                "delete_item_permanently", {"item_id": item_id, "expected_version": version, "confirm": False}
            )
            assert refused.is_error is True
            # The SDK prefixes a deliberate ToolError's text with "Error executing
            # tool <name>: "; the structured {code, message, details} JSON we raised
            # still follows intact, so extract it from the first '{'.
            text = refused.content[0].text
            payload = json.loads(text[text.index("{") :])
            assert payload["code"] == "confirmation_required"


def test_mcp_stdio_protocol_roundtrip(live_api):
    base_url, token = live_api
    asyncio.run(_run_protocol_check(base_url, token))
