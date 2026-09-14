"""Item relation link/unlink tools."""

import uuid
from typing import Literal

from traceback_mcp.errors import guarded
from traceback_mcp.runtime import get_client


@guarded
def link_items(
    from_item_id: uuid.UUID,
    from_expected_version: int,
    relation: Literal["part_of", "about", "related_to"],
    to_item_id: uuid.UUID,
    to_expected_version: int,
    idempotency_key: str | None = None,
) -> dict:
    """Add an association between two items. `part_of` must target a project or a folder (nested to unlimited depth, like a filesystem); rejected if it would make a folder contain itself, directly or through an ancestor. Exactly like `move_item`, a `part_of` link atomically syncs the source item's category: a project always means the Projects category, a folder means whatever category the folder itself currently has (staying in Inbox if the folder is still unclassified)."""
    body = {
        "from_item_id": str(from_item_id),
        "from_expected_version": from_expected_version,
        "relation": relation,
        "to_item_id": str(to_item_id),
        "to_expected_version": to_expected_version,
    }
    return get_client().create_relation(body, idempotency_key=idempotency_key)


@guarded
def unlink_items(relation_id: uuid.UUID, from_expected_version: int, to_expected_version: int, idempotency_key: str | None = None) -> dict:
    """Remove an association by its relation ID. Both endpoints' versions change; re-read them after."""
    body = {"from_expected_version": from_expected_version, "to_expected_version": to_expected_version}
    return get_client().delete_relation(str(relation_id), body, idempotency_key=idempotency_key)
