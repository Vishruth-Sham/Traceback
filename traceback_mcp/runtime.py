"""Process-wide REST client access, kept out of tool modules for testability.

Tests substitute a fake client with `set_client`; the stdio entrypoint
leaves the client unset so the first tool call lazily builds a real one
from environment settings.
"""

from traceback_mcp.config import get_settings
from traceback_mcp.rest_client import RestClient

_client: RestClient | None = None


def get_client() -> RestClient:
    global _client
    if _client is None:
        _client = RestClient(get_settings())
    return _client


def set_client(client: RestClient | None) -> None:
    global _client
    _client = client
