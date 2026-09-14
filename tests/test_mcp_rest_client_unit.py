"""Unit tests for traceback_mcp.rest_client's failure handling.

No network: `urllib.request.urlopen` is monkeypatched to simulate a read
timeout and a 200 response with a malformed body, verifying both become
safe, structured errors instead of an unhandled `TimeoutError` or
`json.JSONDecodeError` escaping the client.
"""

import pytest

from traceback_mcp import rest_client as rc
from traceback_mcp.config import McpSettings
from traceback_mcp.rest_client import BackendUnavailableError, RestClient, RestError


def make_client() -> RestClient:
    settings = McpSettings(api_base_url="http://127.0.0.1:8000", api_token="x" * 24)
    return RestClient(settings)


def test_read_timeout_becomes_backend_unavailable_error(monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(rc.urllib.request, "urlopen", raise_timeout)
    with pytest.raises(BackendUnavailableError) as exc:
        make_client().request("GET", "/api/v1/categories")
    assert "timed out" in str(exc.value)


class _FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_malformed_json_on_success_becomes_structured_rest_error(monkeypatch):
    monkeypatch.setattr(rc.urllib.request, "urlopen", lambda *a, **k: _FakeResponse(b"not json{{{"))
    with pytest.raises(RestError) as exc:
        make_client().request("GET", "/api/v1/categories")
    assert exc.value.code == "invalid_response"
    assert exc.value.status == 200
    # The raw malformed body must never leak into the structured error.
    assert "not json" not in exc.value.message
    assert "not json" not in str(exc.value.details)


def test_valid_json_on_success_still_parses_normally(monkeypatch):
    monkeypatch.setattr(rc.urllib.request, "urlopen", lambda *a, **k: _FakeResponse(b'{"ok": true}'))
    assert make_client().request("GET", "/api/v1/categories") == {"ok": True}


def test_no_content_response_returns_none(monkeypatch):
    monkeypatch.setattr(rc.urllib.request, "urlopen", lambda *a, **k: _FakeResponse(b"", status=204))
    assert make_client().request("DELETE", "/api/v1/items/x") is None
