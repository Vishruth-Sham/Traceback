"""Shared helpers for tool modules."""

from traceback_mcp.config import get_settings

IDEMPOTENCY_KEY_DOC = (
    "Optional idempotency key scoped to this operation and the adapter's client "
    "label. Reusing a key with the same arguments replays the prior result; "
    "reusing it with different arguments returns a conflict."
)


def bounded_limit(limit: int) -> int:
    return max(1, min(limit, get_settings().max_list_limit))
