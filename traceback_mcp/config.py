"""Environment-only configuration for the MCP adapter.

Reads the same ignored `.env` used by the backend/processor. The adapter
never accepts secrets or the backend URL as command-line arguments (to
avoid leaking the bearer token in process listings) and never falls back
to a non-loopback or non-HTTP backend URL.

`.env` is resolved from this package's own location, not the process's
current working directory: an MCP client may launch `python -m
traceback_mcp` with any cwd, and pydantic-settings' default `env_file="
.env"` would silently find nothing (falling back to defaults, or failing
validation) if that cwd is not the repository root. Real environment
variables still take precedence over `.env` file values either way — this
only changes where the file is discovered, not the override order.
"""

import ipaddress
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _REPO_ROOT / ".env"


def _is_loopback_http(value: str) -> bool:
    parsed = urlparse(value)
    host = parsed.hostname
    try:
        loopback = host == "localhost" or (host is not None and ipaddress.ip_address(host).is_loopback)
    except ValueError:
        loopback = False
    return parsed.scheme == "http" and loopback and not parsed.username and not parsed.password


class McpSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRACEBACK_MCP_", env_file=_ENV_FILE, extra="ignore")

    api_base_url: str = "http://127.0.0.1:8000"
    api_token: str = Field(min_length=1, validation_alias=AliasChoices("API_TOKEN", "TRACEBACK_API_TOKEN"))
    request_timeout_s: float = Field(default=30.0, gt=0)
    client_label: str = "mcp"
    max_list_limit: int = Field(default=100, ge=1, le=250)

    @field_validator("api_base_url")
    @classmethod
    def api_must_be_loopback(cls, value: str) -> str:
        if not _is_loopback_http(value):
            raise ValueError("backend API URL must be plain HTTP on a loopback address")
        return value


@lru_cache
def get_settings() -> McpSettings:
    return McpSettings()  # type: ignore[call-arg]
