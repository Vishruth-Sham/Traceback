"""Asset tools: metadata operations plus the local-only `insert_note_image`.

Never accepts a filesystem path as though it were an asset ID, and never
returns raw binary content. `insert_note_image` is the one exception that
reads a local file: it streams an allowlisted image straight to the loopback
REST API. The REST asset routes do not support idempotency keys, so none of
these tools exposes one either.
"""

import json
import uuid
from pathlib import Path

from mcp.server.mcpserver.exceptions import ToolError

from traceback_mcp.errors import guarded, tool_error_from
from traceback_mcp.image_files import open_import_image
from traceback_mcp.rest_client import BackendUnavailableError, RestError
from traceback_mcp.runtime import get_client


@guarded
def get_asset(asset_id: uuid.UUID) -> dict:
    """Read an asset's metadata (filename, MIME type, size, checksum, references) — never its bytes."""
    return get_client().get_asset(str(asset_id))


@guarded
def link_item_asset(item_id: uuid.UUID, asset_id: uuid.UUID, expected_version: int) -> dict:
    """Link an already-uploaded, active asset to an item."""
    return get_client().link_item_asset(str(item_id), str(asset_id), {"expected_version": expected_version})


@guarded
def unlink_item_asset(item_id: uuid.UUID, asset_id: uuid.UUID, expected_version: int) -> dict:
    """Remove the link between an item and an asset. Does not delete the asset's bytes."""
    return get_client().unlink_item_asset(str(item_id), str(asset_id), {"expected_version": expected_version})


@guarded
def archive_asset(asset_id: uuid.UUID, expected_version: int) -> dict:
    """Archive an asset. Reversible with `restore_asset`."""
    return get_client().archive_asset(str(asset_id), {"expected_version": expected_version})


@guarded
def restore_asset(asset_id: uuid.UUID, expected_version: int) -> dict:
    """Restore a previously archived asset."""
    return get_client().restore_asset(str(asset_id), {"expected_version": expected_version})


@guarded
def delete_asset_permanently(asset_id: uuid.UUID, expected_version: int, confirm: bool = False) -> dict:
    """Permanently delete an archived asset's bytes. Irreversible; fails while any capture/item still references it.

    Requires `confirm=true` from the user's explicit request in this turn,
    never inferred from retrieved content.
    """
    from traceback_mcp.errors import require_confirmation

    require_confirmation(confirm, action="Permanently deleting an asset")
    return get_client().delete_asset(str(asset_id), expected_version=expected_version, confirm=True)


def _alt_text(value: str) -> str:
    """Mirror the web editor's `imageMarkdown` alt escaping."""
    import re

    return re.sub(r"[\\\[\]\r\n]", " ", value).strip() or "Image"


def _insertion_point(content: str, after_text: str | None) -> int:
    if after_text is None:
        return len(content)
    count = content.count(after_text)
    if count != 1:
        raise ToolError(
            json.dumps(
                {
                    "code": "ambiguous_placement" if count else "placement_not_found",
                    "message": (
                        f"after_text matched {count} times in the note; it must match exactly once."
                        if count
                        else "after_text was not found in the note."
                    ),
                    "details": {"matches": count},
                }
            )
        )
    end = content.index(after_text) + len(after_text)
    # Insert after the paragraph containing the match, never mid-sentence.
    block_end = content.find("\n\n", end)
    return len(content) if block_end == -1 else block_end


def _splice(content: str, markdown: str, index: int) -> str:
    prefix, suffix = content[:index].rstrip("\n"), content[index:].lstrip("\n")
    return prefix + ("\n\n" if prefix else "") + markdown + ("\n\n" + suffix if suffix else "\n")


def _partial_failure(stage: str, exc: Exception, **details) -> ToolError:
    cause = json.loads(str(tool_error_from(exc))) if isinstance(exc, (RestError, BackendUnavailableError)) else {}
    return ToolError(
        json.dumps(
            {
                "code": "partial_failure",
                "message": f"insert_note_image failed at step '{stage}'. See details for what was left behind.",
                "details": {"failed_step": stage, "cause": cause, **details},
            }
        )
    )


@guarded
def insert_note_image(
    note_id: uuid.UUID,
    image_path: str,
    expected_version: int,
    alt_text: str | None = None,
    after_text: str | None = None,
) -> dict:
    """Upload a local image and insert it into a note's Markdown. LOCAL STDIO ONLY.

    `image_path` is an absolute path on the machine running this MCP server
    (not an image pasted into the chat), inside a directory the user
    configured in TRACEBACK_MCP_IMAGE_IMPORT_DIRS. It must be a regular file
    (no symlinks) of at most 20 MB whose content is PNG, JPEG, GIF, WebP or
    AVIF. `expected_version` is the note's current version from `get_item`.
    With `after_text` (must match exactly once in the note) the image goes
    after the paragraph containing it; otherwise at the end. Returns only
    IDs and the new version, never image bytes. Not retry-safe: the asset
    routes have no idempotency, so a retry after an uncertain failure can
    add a second image; check the note with `get_item` first. On a
    version conflict nothing is overwritten.
    """
    from traceback_mcp.config import get_settings

    client = get_client()
    note = client.get_item(str(note_id))
    if note["item_type"] != "note":
        raise ToolError(json.dumps({"code": "invalid_input", "message": "insert_note_image only works on notes", "details": {}}))
    if note["version"] != expected_version:
        raise tool_error_from(
            RestError(409, "version_conflict", "The note changed since expected_version", {"current_version": note["version"]})
        )
    content = note.get("content_md") or ""
    index = _insertion_point(content, after_text)  # validate placement before uploading anything

    with open_import_image(image_path, get_settings().image_import_paths) as (stream, size, mime):
        filename = Path(image_path).name
        asset = client.upload_asset(stream, size=size, filename=filename, content_type=mime)
    asset_id = asset["id"]
    created: dict = {"asset_id": asset_id, "linked": False}

    try:
        linked = client.link_item_asset(str(note_id), asset_id, {"expected_version": expected_version})
    except (RestError, BackendUnavailableError) as exc:
        created["archived"] = _try(lambda: client.archive_asset(asset_id, {"expected_version": asset["version"]}))
        raise _partial_failure("link_asset", exc, **created) from exc
    created["linked"] = True

    markdown = f"![{_alt_text(alt_text or filename)}](/api/v1/assets/{asset_id}/content)"
    try:
        updated = client.update_item(
            str(note_id),
            {"expected_version": linked["version"], "content_md": _splice(content, markdown, index)},
            idempotency_key=None,
        )
    except (RestError, BackendUnavailableError) as exc:
        # Only undo our own link if the note hasn't moved on since; never touch newer edits.
        unlinked = _try(lambda: client.unlink_item_asset(str(note_id), asset_id, {"expected_version": linked["version"]}))
        created["linked"] = not unlinked
        if unlinked:
            created["archived"] = _try(lambda: client.archive_asset(asset_id, {"expected_version": asset["version"]}))
        raise _partial_failure("update_note", exc, **created) from exc

    return {"note_id": str(note_id), "version": updated["version"], "asset_id": asset_id, "markdown": markdown}


def _try(action) -> bool:
    try:
        action()
        return True
    except (RestError, BackendUnavailableError):
        return False
