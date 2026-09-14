"""Item-to-capture provenance link/unlink/list tools."""

import uuid

from traceback_mcp.errors import guarded
from traceback_mcp.runtime import get_client


@guarded
def get_item_sources(item_id: uuid.UUID) -> list[dict]:
    """List the captures an item is linked to as provenance."""
    return get_client().get_item_sources(str(item_id))


@guarded
def link_item_source(
    item_id: uuid.UUID,
    capture_id: uuid.UUID,
    item_expected_version: int,
    capture_expected_version: int,
    idempotency_key: str | None = None,
) -> dict:
    """Manually link an existing item to an existing capture as a source."""
    body = {
        "capture_id": str(capture_id),
        "item_expected_version": item_expected_version,
        "capture_expected_version": capture_expected_version,
    }
    return get_client().link_item_source(str(item_id), body, idempotency_key=idempotency_key)


@guarded
def unlink_item_source(
    item_id: uuid.UUID,
    source_id: uuid.UUID,
    item_expected_version: int,
    capture_expected_version: int,
    idempotency_key: str | None = None,
) -> dict:
    """Remove a source link between an item and a capture. Required before deleting a still-referenced capture."""
    body = {"item_expected_version": item_expected_version, "capture_expected_version": capture_expected_version}
    return get_client().unlink_item_source(str(item_id), str(source_id), body, idempotency_key=idempotency_key)
