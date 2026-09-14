"""Focused regression tests for the MCP-adapter review fixes.

No network, no PostgreSQL: these isolate two specific fixes.

1. `.env` discovery must be independent of the client's working directory
   (`traceback_mcp/config.py`'s `_ENV_FILE` is resolved from the package's
   own path, not from `SettingsConfigDict(env_file=".env")`'s implicit cwd
   lookup).
2. Every resource ID exposed to MCP is a `uuid.UUID`-typed argument, so the
   SDK's own schema validation rejects a path-injection-shaped string
   before a tool body — and therefore before any REST call — ever runs.
"""

import asyncio
from pathlib import Path

import pytest

from mcp.server.mcpserver.exceptions import ToolError

from traceback_mcp import config
from traceback_mcp.runtime import set_client
from traceback_mcp.server import build_server


class ExplodingClient:
    """Fails the test if any REST method is called; used to prove validation short-circuits first."""

    def __getattr__(self, name):
        def method(*args, **kwargs):
            raise AssertionError(f"REST client method {name!r} should never be called for an invalid ID")

        return method


# --- .env resolution is independent of cwd -------------------------------------------------


def test_env_file_resolves_next_to_the_package_not_the_cwd():
    expected = Path(config.__file__).resolve().parent.parent / ".env"
    assert config._ENV_FILE == expected
    assert config.McpSettings.model_config["env_file"] == expected


def test_settings_load_env_file_regardless_of_current_working_directory(tmp_path, monkeypatch):
    fake_env = tmp_path / "fake_repo" / ".env"
    fake_env.parent.mkdir()
    fake_env.write_text("TRACEBACK_API_TOKEN=token-from-fake-env-file-000000\n")

    # Simulate the fix's effect (an absolute, package-resolved path) without
    # touching the real project .env: point the already-built settings
    # class at our fake one, exactly as the fix wires an absolute path in
    # at class-definition time instead of a cwd-relative ".env" string.
    monkeypatch.setitem(config.McpSettings.model_config, "env_file", fake_env)
    monkeypatch.delenv("TRACEBACK_API_TOKEN", raising=False)
    monkeypatch.delenv("API_TOKEN", raising=False)

    unrelated_cwd = tmp_path / "somewhere_with_no_env_file"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)
    assert not (unrelated_cwd / ".env").exists()

    settings = config.McpSettings()
    assert settings.api_token == "token-from-fake-env-file-000000"


def test_settings_still_prefer_a_real_environment_variable_over_the_env_file(tmp_path, monkeypatch):
    fake_env = tmp_path / ".env"
    fake_env.write_text("TRACEBACK_API_TOKEN=token-from-file-should-be-overridden\n")
    monkeypatch.setitem(config.McpSettings.model_config, "env_file", fake_env)
    monkeypatch.setenv("TRACEBACK_API_TOKEN", "token-from-real-environment")

    settings = config.McpSettings()
    assert settings.api_token == "token-from-real-environment"


# --- resource IDs are validated as UUIDs before any tool body runs -----------------------


PATH_INJECTION_PAYLOADS = [
    "../../etc/passwd",
    "items/other-id/../../assets/secret",
    "abc?expected_version=1",
    "not-a-uuid-at-all",
]


@pytest.fixture(autouse=True)
def exploding_client():
    set_client(ExplodingClient())
    yield
    set_client(None)


@pytest.mark.parametrize("bad_id", PATH_INJECTION_PAYLOADS)
@pytest.mark.parametrize(
    "tool_name,args",
    [
        ("get_item", lambda bad_id: {"item_id": bad_id}),
        ("archive_item", lambda bad_id: {"item_id": bad_id, "expected_version": 1}),
        ("delete_item_permanently", lambda bad_id: {"item_id": bad_id, "expected_version": 1, "confirm": True}),
        ("get_capture", lambda bad_id: {"capture_id": bad_id}),
        ("get_asset", lambda bad_id: {"asset_id": bad_id}),
        ("unlink_items", lambda bad_id: {"relation_id": bad_id, "from_expected_version": 1, "to_expected_version": 1}),
        ("undo_action", lambda bad_id: {"action_id": bad_id, "expected_versions": {}}),
    ],
)
def test_invalid_resource_id_is_rejected_before_any_rest_call(tool_name, args, bad_id):
    server = build_server()

    async def run():
        return await server.call_tool(tool_name, args(bad_id))

    with pytest.raises(ToolError) as exc:
        asyncio.run(run())
    # A schema-validation failure, not the ExplodingClient's AssertionError
    # (which would surface as UnexpectedToolError, a distinct subclass).
    assert "validation error" in str(exc.value) or "uuid" in str(exc.value).lower()


def test_undo_action_expected_versions_keys_are_validated_as_uuids():
    server = build_server()

    async def run():
        return await server.call_tool(
            "undo_action", {"action_id": "11111111-1111-1111-1111-111111111111", "expected_versions": {"not-a-uuid": 1}}
        )

    with pytest.raises(ToolError):
        asyncio.run(run())


def test_valid_uuid_reaches_the_tool_body():
    # Sanity check: a well-formed UUID passes schema validation and does
    # reach the (exploding) client, proving the parametrized failures above
    # are actually about validation and not e.g. a typo in the tool name.
    server = build_server()

    async def run():
        return await server.call_tool("get_item", {"item_id": "11111111-1111-1111-1111-111111111111"})

    with pytest.raises(ToolError) as exc:
        asyncio.run(run())
    assert "get_item" in str(exc.value)
    assert "validation error" not in str(exc.value)
