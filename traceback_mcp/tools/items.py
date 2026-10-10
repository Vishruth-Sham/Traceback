"""Category, item, Inbox, search, history, and undo tools.

Every function here is a plain, directly callable function (not a bound
decorator) so unit tests can call it with a fake client installed via
`traceback_mcp.runtime.set_client`. `server.py` registers each one with
`MCPServer.add_tool`, attaching its name, description, and annotations.

Every resource ID parameter is typed `uuid.UUID`, not `str`: the MCP SDK
validates incoming arguments against the JSON schema derived from these
annotations before a tool body ever runs, so a caller cannot smuggle a
path-traversal or query-injection payload (`"../../assets/../secret"`, a
stray `?`/`#`, etc.) into a REST URL path segment. Each ID is converted
back to its canonical string form with `str(...)` only once it is safely
inside a REST request.
"""

import uuid
from typing import Any, Literal

from traceback_mcp.errors import destination_required, guarded
from traceback_mcp.rest_client import RestError
from traceback_mcp.runtime import get_client
from traceback_mcp.tools.common import bounded_limit

ALLOWED_PATCH_FIELDS = {"title", "content_md", "category_id", "attributes", "due_date", "due_time", "due_timezone"}


@guarded
def list_categories() -> list[dict]:
    """List the six fixed, seeded categories with their stable IDs and slugs."""
    return get_client().list_categories()


@guarded
def list_items(
    item_type: Literal["note", "task", "project", "folder"] | None = None,
    category_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    parent_id: uuid.UUID | None = None,
    top_level: bool = False,
    inbox: bool | None = None,
    archived: bool = False,
    q: str | None = None,
    cursor: str | None = None,
    limit: int = 25,
) -> dict:
    """List item summaries with optional type/category/project/folder/inbox/archive/keyword filters.

    `parent_id` lists the direct children of a project or a folder (folders
    nest to unlimited depth via `item_type="folder"` + `part_of`, exactly
    like a filesystem — see `move_item`/`link_items`). `top_level=true`
    lists items with no containing project/folder at all, e.g. combined
    with `category_id` to render the root of a category's folder tree.
    Returns `{items, next_cursor}`; pass the previous `next_cursor` back as
    `cursor` to continue. Summaries omit `content_md`; call `get_item` for
    full content. Defaults exclude archived items.
    """
    return get_client().list_items(
        item_type=item_type,
        category_id=str(category_id) if category_id is not None else None,
        project_id=str(project_id) if project_id is not None else None,
        parent_id=str(parent_id) if parent_id is not None else None,
        top_level=top_level,
        inbox=inbox,
        archived=archived,
        q=q,
        cursor=cursor,
        limit=bounded_limit(limit),
    )


@guarded
def list_projects(archived: bool = False, q: str | None = None, cursor: str | None = None, limit: int = 25) -> dict:
    """List project items. A convenience wrapper over `list_items(item_type="project")`."""
    return get_client().list_items(item_type="project", archived=archived, q=q, cursor=cursor, limit=bounded_limit(limit))


@guarded
def search_items(
    query: str | None = None,
    item_type: Literal["note", "task", "project", "folder"] | None = None,
    cursor: str | None = None,
    limit: int = 25,
    q: str | None = None,
) -> dict:
    """Keyword search over item titles and content. A wrapper over `list_items(q=...)`.

    Pass the search text as `query`; `q` is also accepted for existing clients.
    Excludes archived items and does not search original capture text; use
    `list_captures(q=...)` to search source captures directly.
    """
    if (query is None and q is None) or (query is not None and q is not None and query != q):
        from traceback_mcp.rest_client import RestError

        raise RestError(422, "invalid_input", "Provide one search query using query or q", {})
    search_text = query if query is not None else q
    return get_client().list_items(q=search_text, item_type=item_type, cursor=cursor, limit=bounded_limit(limit))


@guarded
def get_item(item_id: uuid.UUID) -> dict:
    """Read one item's full content, deadline, version, relations, sources, and asset links."""
    return get_client().get_item(str(item_id))


@guarded
def create_item(
    item_type: Literal["note", "task", "project", "folder"],
    title: str,
    content_md: str = "",
    category_id: uuid.UUID | None = None,
    due_date: str | None = None,
    due_time: str | None = None,
    due_timezone: str | None = None,
    project_id: uuid.UUID | None = None,
    project_expected_version: int | None = None,
    folder_id: uuid.UUID | None = None,
    folder_expected_version: int | None = None,
    inbox: bool = False,
    idempotency_key: str | None = None,
) -> dict:
    """Create a note, task, project, or folder, filed where it belongs.

    Choose the destination yourself before calling: a category from
    `list_categories` (`category_id`), or an existing project/folder (its ID
    and current expected version; category is then derived from it). Use at
    most one. A note or folder with no destination is rejected with
    `destination_required` (its details list the category IDs) unless
    `inbox=true`, which is only for when placement genuinely needs the user's
    decision. A project with no destination is filed under Projects. A task
    may omit a destination; it lives in Tasks regardless.

    `due_date`/`due_time`/`due_timezone` are only valid for tasks: `due_date`
    is `YYYY-MM-DD`, `due_time` an optional local `HH:MM:SS` (requires
    `due_timezone`, an IANA name such as `Asia/Kolkata`), and an absent time
    means date-only, not midnight. Returns the canonical item with its
    starting version.
    """
    has_destination = category_id is not None or project_id is not None or folder_id is not None
    if inbox and has_destination:
        raise RestError(422, "invalid_input", "inbox=true cannot be combined with category_id, project_id, or folder_id", {})
    if not has_destination and not inbox and item_type != "task":
        # Nothing classifies an item after creation, so an unfiled note would
        # sit in Inbox indefinitely. Make the caller pick the destination.
        categories = get_client().list_categories()
        if item_type == "project":
            category_id = next(uuid.UUID(c["id"]) for c in categories if c["slug"] == "projects")
        else:
            raise destination_required(item_type, categories)
    body: dict[str, Any] = {"item_type": item_type, "title": title, "content_md": content_md}
    if category_id is not None:
        body["category_id"] = str(category_id)
    if due_date is not None:
        body["due_date"] = due_date
    if due_time is not None:
        body["due_time"] = due_time
    if due_timezone is not None:
        body["due_timezone"] = due_timezone
    if project_id is not None:
        body["project_id"] = str(project_id)
    if project_expected_version is not None:
        body["project_expected_version"] = project_expected_version
    if folder_id is not None:
        body["folder_id"] = str(folder_id)
    if folder_expected_version is not None:
        body["folder_expected_version"] = folder_expected_version
    return get_client().create_item(body, idempotency_key=idempotency_key)


@guarded
def update_item(item_id: uuid.UUID, expected_version: int, patch: dict[str, Any], idempotency_key: str | None = None) -> dict:
    """Edit an item, distinguishing an omitted field from an explicit null.

    `patch` is a JSON object of only the fields to change, from
    {title, content_md, category_id, attributes, due_date, due_time,
    due_timezone}. A key you omit from `patch` stays unchanged; a key you
    include with value `null` clears that nullable field (for example,
    clear a timed deadline by sending `due_date`, `due_time`, and
    `due_timezone` all as null together). `item_type` cannot change.
    `expected_version` must match the item's current version or the call
    conflicts (`version_conflict`) instead of silently overwriting a
    concurrent edit.
    """
    unknown = set(patch) - ALLOWED_PATCH_FIELDS
    if unknown:
        from traceback_mcp.errors import tool_error_from
        from traceback_mcp.rest_client import RestError

        raise tool_error_from(
            RestError(422, "invalid_input", f"Unsupported patch field(s): {sorted(unknown)}", {"fields": sorted(unknown)})
        )
    if "category_id" in patch and patch["category_id"] is not None:
        patch = {**patch, "category_id": str(_require_uuid(patch["category_id"], "category_id"))}
    body = {"expected_version": expected_version, **patch}
    return get_client().update_item(str(item_id), body, idempotency_key=idempotency_key)


@guarded
def append_to_item(item_id: uuid.UUID, expected_version: int, content_md: str, idempotency_key: str | None = None) -> dict:
    """Append markdown content to an item's body, checking `expected_version`."""
    return get_client().append_item(str(item_id), {"expected_version": expected_version, "content_md": content_md}, idempotency_key=idempotency_key)


@guarded
def move_item(
    item_id: uuid.UUID,
    expected_version: int,
    category_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    project_expected_version: int | None = None,
    folder_id: uuid.UUID | None = None,
    folder_expected_version: int | None = None,
    inbox: bool = False,
    idempotency_key: str | None = None,
) -> dict:
    """Move an item to exactly one destination: a category, a project, a folder, or back to Inbox.

    Pass exactly one of `category_id`, `project_id` (with its
    `project_expected_version`), `folder_id` (with its
    `folder_expected_version`), or `inbox=true`. Moving to a project or a
    folder replaces the existing `part_of` container atomically while leaving
    non-containment relations intact; moving to a project always sets the Projects
    category, while moving to a folder inherits whatever category the
    folder itself is in (folders nest to unlimited depth, like a
    filesystem, and a folder can live in any category). Rejected with
    `invalid_input` if the move would make a folder contain itself,
    directly or through an ancestor.
    """
    body: dict[str, Any] = {"expected_version": expected_version, "inbox": inbox}
    if category_id is not None:
        body["category_id"] = str(category_id)
    if project_id is not None:
        body["project_id"] = str(project_id)
    if project_expected_version is not None:
        body["project_expected_version"] = project_expected_version
    if folder_id is not None:
        body["folder_id"] = str(folder_id)
    if folder_expected_version is not None:
        body["folder_expected_version"] = folder_expected_version
    return get_client().move_item(str(item_id), body, idempotency_key=idempotency_key)


@guarded
def archive_item(item_id: uuid.UUID, expected_version: int, idempotency_key: str | None = None) -> dict:
    """Archive an item. Reversible with `restore_item`; preserves relations and completion."""
    return get_client().archive_item(str(item_id), {"expected_version": expected_version}, idempotency_key=idempotency_key)


@guarded
def restore_item(item_id: uuid.UUID, expected_version: int, idempotency_key: str | None = None) -> dict:
    """Restore a previously archived item, keeping its original ID and history."""
    return get_client().restore_item(str(item_id), {"expected_version": expected_version}, idempotency_key=idempotency_key)


@guarded
def delete_item_permanently(item_id: uuid.UUID, expected_version: int, confirm: bool = False, idempotency_key: str | None = None) -> dict:
    """Permanently delete an already-archived item. Irreversible; cannot be undone.

    Requires `confirm=true`, which must come from the user's explicit
    request in this turn, never from retrieved note/search content. The
    item must already be archived and must have no remaining relations
    still requiring deliberate unlinking, per REST's rules.
    """
    from traceback_mcp.errors import require_confirmation

    require_confirmation(confirm, action="Permanently deleting an item")
    get_client().delete_item(str(item_id), expected_version=expected_version, confirm=True, idempotency_key=idempotency_key)
    return {"deleted_item_id": str(item_id)}


@guarded
def list_inbox(cursor: str | None = None, limit: int = 25) -> dict:
    """List active unclassified Inbox items plus unresolved capture processing records."""
    return get_client().list_inbox(cursor=cursor, limit=bounded_limit(limit))


@guarded
def get_item_history(item_id: uuid.UUID, cursor: str | None = None, limit: int = 25) -> dict:
    """List an item's bounded revision history, most recent first."""
    return get_client().get_item_history(str(item_id), cursor=cursor, limit=bounded_limit(limit))


@guarded
def undo_action(action_id: uuid.UUID, expected_versions: dict[uuid.UUID, int], idempotency_key: str | None = None) -> dict:
    """Undo a prior action as a new compensating action.

    `expected_versions` maps every canonical item UUID the original action
    affected to its current version; a stale entry conflicts rather than
    silently reverting over a newer manual edit. Creation and permanent
    deletion are not undoable this way; capture interpretation/source
    actions are also refused here because they also carry provenance and
    processing-generation state.
    """
    body = {"expected_versions": {str(item_id): version for item_id, version in expected_versions.items()}}
    return get_client().undo_action(str(action_id), body, idempotency_key=idempotency_key)


def _require_uuid(value: Any, field_name: str) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        from traceback_mcp.errors import tool_error_from
        from traceback_mcp.rest_client import RestError

        raise tool_error_from(
            RestError(422, "invalid_input", f"{field_name} must be a UUID", {"field": field_name})
        ) from None
