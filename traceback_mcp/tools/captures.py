"""Capture create/list/read/correct/retry/archive/restore/delete and manual interpretation.

Processor-only lease operations (`claim`/`fail`) are deliberately not
exposed here: they exist to let the bounded local processor safely hand
back a durable failure under an active lease it holds, which an MCP client
never does. Exposing them would let a client fence out or corrupt the
processor's own in-flight work without a documented need.
"""

import uuid
from typing import Any, Literal

from traceback_mcp.errors import guarded
from traceback_mcp.runtime import get_client
from traceback_mcp.tools.common import bounded_limit


@guarded
def create_capture(
    source_type: Literal["typed", "audio", "file", "url", "import"],
    raw_text: str | None = None,
    description: str | None = None,
    url: str | None = None,
    captured_at: str | None = None,
    source_date: str | None = None,
    source_timezone: str | None = None,
    timestamp_origin: Literal["user_supplied", "client_supplied", "source_metadata", "unknown"] = "unknown",
    asset_ids: list[uuid.UUID] | None = None,
    client_app: str | None = None,
    external_source_id: str | None = None,
    contextual_item_id: uuid.UUID | None = None,
    timestamp_precision: Literal["exact", "date", "approximate", "unknown"] = "unknown",
    supplied_title: str | None = None,
    supplied_author: str | None = None,
    supplied_published_date: str | None = None,
    processing_profile: Literal["general", "task_quick_add", "note_quick_add"] = "general",
    placement_hint: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Persist an original capture before any interpretation.

    Typed captures require non-blank `raw_text`; audio/file captures
    require at least one already-uploaded asset ID in `asset_ids` (upload
    the bytes through REST `POST /assets` first — this adapter never
    accepts or embeds raw binary content). `captured_at` must include a UTC
    offset. `client_app`/`external_source_id`/`contextual_item_id`/
    `timestamp_precision`/`supplied_title`/`supplied_author`/
    `supplied_published_date` populate the capture's bounded source metadata
    (see `docs/backend-plan.md`'s file/time/source metadata table);
    `contextual_item_id` is the ID of an item this capture was made in
    reference to, and `supplied_published_date` is `YYYY-MM-DD`. Returns the
    capture's ID, state, and asset IDs; it is not yet interpreted into items.
    """
    body: dict[str, Any] = {
        "source_type": source_type,
        "timestamp_origin": timestamp_origin,
        "asset_ids": [str(asset_id) for asset_id in asset_ids] if asset_ids else [],
    }
    if raw_text is not None:
        body["raw_text"] = raw_text
    if description is not None:
        body["description"] = description
    if url is not None:
        body["url"] = url
    if captured_at is not None:
        body["captured_at"] = captured_at
    if source_date is not None:
        body["source_date"] = source_date
    if source_timezone is not None:
        body["source_timezone"] = source_timezone
    metadata: dict[str, Any] = {}
    if processing_profile != "general":
        metadata["processing_profile"] = processing_profile
    if client_app is not None:
        metadata["client_app"] = client_app
    if external_source_id is not None:
        metadata["external_source_id"] = external_source_id
    if contextual_item_id is not None:
        metadata["contextual_item_id"] = str(contextual_item_id)
    if timestamp_precision != "unknown":
        metadata["timestamp_precision"] = timestamp_precision
    if supplied_title is not None:
        metadata["supplied_title"] = supplied_title
    if supplied_author is not None:
        metadata["supplied_author"] = supplied_author
    if supplied_published_date is not None:
        metadata["supplied_published_date"] = supplied_published_date
    if placement_hint is not None:
        metadata["placement_hint"] = placement_hint
    if metadata:
        body["metadata"] = metadata
    return get_client().create_capture(body, idempotency_key=idempotency_key)


@guarded
def list_captures(
    archived: bool = False,
    state: Literal["pending", "processing", "awaiting_review", "failed", "resolved"] | None = None,
    source_type: Literal["typed", "audio", "file", "url", "import"] | None = None,
    q: str | None = None,
    cursor: str | None = None,
    limit: int = 25,
) -> dict:
    """List recent captures. Summaries omit `raw_text`; call `get_capture` for full content."""
    return get_client().list_captures(archived=archived, state=state, source_type=source_type, q=q, cursor=cursor, limit=bounded_limit(limit))


@guarded
def get_capture(capture_id: uuid.UUID) -> dict:
    """Read one capture's original data, effective corrections, asset IDs, resulting item IDs, and processing status."""
    return get_client().get_capture(str(capture_id))


@guarded
def correct_capture(
    capture_id: uuid.UUID,
    expected_version: int,
    corrections: dict[str, Any],
    idempotency_key: str | None = None,
) -> dict:
    """Add a versioned descriptive correction without rewriting the original capture.

    `corrections` is a JSON object with at least one of {description, url,
    captured_at, source_date, source_timezone, note}; only the fields you
    include are changed. The original `raw_text` can never be corrected
    through this operation.
    """
    allowed = {"description", "url", "captured_at", "source_date", "source_timezone", "note", "note_text", "supplied_title", "placement_hint"}
    unknown = set(corrections) - allowed
    if unknown:
        from traceback_mcp.errors import tool_error_from
        from traceback_mcp.rest_client import RestError

        raise tool_error_from(RestError(422, "invalid_input", f"Unsupported correction field(s): {sorted(unknown)}", {"fields": sorted(unknown)}))
    body = {"expected_version": expected_version, **corrections}
    return get_client().correct_capture(str(capture_id), body, idempotency_key=idempotency_key)


@guarded
def archive_capture(capture_id: uuid.UUID, expected_version: int, idempotency_key: str | None = None) -> dict:
    """Archive a capture. Reversible with `restore_capture`."""
    return get_client().archive_capture(str(capture_id), {"expected_version": expected_version}, idempotency_key=idempotency_key)


@guarded
def restore_capture(capture_id: uuid.UUID, expected_version: int, idempotency_key: str | None = None) -> dict:
    """Restore a previously archived capture."""
    return get_client().restore_capture(str(capture_id), {"expected_version": expected_version}, idempotency_key=idempotency_key)


@guarded
def delete_capture_permanently(capture_id: uuid.UUID, expected_version: int, confirm: bool = False, idempotency_key: str | None = None) -> dict:
    """Permanently delete an already-archived capture. Irreversible; does not delete resulting items or asset bytes.

    Requires `confirm=true` from the user's explicit request in this turn,
    never inferred from retrieved content. Fails with `linked_source_conflict`
    while any item still references this capture; unlink those sources
    first with `unlink_item_source`.
    """
    from traceback_mcp.errors import require_confirmation

    require_confirmation(confirm, action="Permanently deleting a capture")
    get_client().delete_capture(str(capture_id), expected_version=expected_version, confirm=True, idempotency_key=idempotency_key)
    return {"deleted_capture_id": str(capture_id)}


@guarded
def retry_capture(capture_id: uuid.UUID, expected_version: int, expected_generation: int, idempotency_key: str | None = None) -> dict:
    """Requeue a failed capture for another processing attempt. Does not guarantee a processor is running."""
    body = {"expected_version": expected_version, "expected_generation": expected_generation}
    return get_client().retry_capture(str(capture_id), body, idempotency_key=idempotency_key)


@guarded
def apply_capture_interpretation(
    capture_id: uuid.UUID,
    expected_version: int,
    expected_generation: int,
    items: list[dict[str, Any]],
    transcript: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Atomically create/append items from a capture and record provenance, in manual mode only.

    Always runs as `mode="manual"` (this adapter never holds a processor
    lease and never accepts one); manual interpretation still fences out a
    late automated attempt by advancing the processing generation. `items`
    is a list of 1-10 objects, each either
    `{"kind": "create", "item": {<create_item fields>}}` or
    `{"kind": "append", "item_id", "expected_version", "content_md"}`. A
    "create" operation may optionally add `project_id`+`project_expected_version`
    or `folder_id`+`folder_expected_version` (never both) to place the new
    item directly inside that project/folder atomically with its creation;
    `item.category_id` must then be omitted, since it is derived from the
    container. Any invalid operation rolls the whole batch back.
    """
    body: dict[str, Any] = {
        "expected_version": expected_version,
        "expected_generation": expected_generation,
        "mode": "manual",
        "items": items,
    }
    if transcript is not None:
        body["transcript"] = transcript
    return get_client().apply_capture_interpretation(str(capture_id), body, idempotency_key=idempotency_key)
