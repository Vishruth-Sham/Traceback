"""Safe, metadata-only asset tools.

Never accepts a filesystem path as though it were an asset ID, and never
returns or accepts raw binary content: upload/download flow through REST
`POST /assets` and `GET /assets/{id}/content` directly, outside this
adapter. These REST asset routes do not support idempotency keys, so
these tools do not expose one either.
"""

import uuid

from traceback_mcp.errors import guarded
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
