"""Builds the MCP server and registers the full tool catalog with annotations.

Reads never mutate and are marked `readOnlyHint=True, openWorldHint=False`
(closed-world: every read stays inside this one local backend). Per the MCP
spec, `idempotentHint` "is meaningful only when readOnlyHint == false", so
read tools deliberately omit it rather than setting it to a value the spec
says to ignore. Reversible mutations are marked `readOnlyHint=False,
destructiveHint=False, idempotentHint=False` (repeating one with the same
arguments is not a no-op: `expected_version` must advance between calls).
Irreversible operations are marked `destructiveHint=True` and additionally
require an explicit `confirm=true` tool argument, enforced in the tool body
itself (see `traceback_mcp.errors.require_confirmation`) so the annotation
is backed by a real runtime check, not just a hint a client may ignore.

Imports `MCPServer` from the public `mcp.server` package rather than the
`mcp.server.mcpserver` submodule it is implemented in.
"""

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from traceback_mcp.tools import assets, captures, items, log, relations, sources, tasks

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
MUTATE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
DESTROY = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)

# Tools that read the local filesystem. They exist only on this stdio server and
# must never be registered on a remote MCP endpoint, where a path would name the
# server's files rather than the caller's.
LOCAL_ONLY_TOOLS = frozenset({"insert_note_image"})

# (function, title, annotations)
_TOOLS = [
    # Categories, items, Inbox, search, history, undo
    (items.list_categories, "List categories", READ),
    (items.list_items, "List items", READ),
    (items.list_projects, "List projects", READ),
    (items.search_items, "Search items", READ),
    (items.get_item, "Get item", READ),
    (items.create_item, "Create item", MUTATE),
    (items.update_item, "Update item", MUTATE),
    (items.append_to_item, "Append to item", MUTATE),
    (items.move_item, "Move item", MUTATE),
    (items.archive_item, "Archive item", MUTATE),
    (items.restore_item, "Restore item", MUTATE),
    (items.delete_item_permanently, "Permanently delete item", DESTROY),
    (items.list_inbox, "List Inbox", READ),
    (items.get_item_history, "Get item history", READ),
    (items.undo_action, "Undo action", MUTATE),
    # Tasks
    (tasks.list_tasks, "List tasks", READ),
    (tasks.complete_task, "Complete task", MUTATE),
    (tasks.reopen_task, "Reopen task", MUTATE),
    # Relations
    (relations.link_items, "Link items", MUTATE),
    (relations.unlink_items, "Unlink items", MUTATE),
    # Captures
    (captures.create_capture, "Create capture", MUTATE),
    (captures.list_captures, "List captures", READ),
    (captures.get_capture, "Get capture", READ),
    (captures.correct_capture, "Correct capture", MUTATE),
    (captures.archive_capture, "Archive capture", MUTATE),
    (captures.restore_capture, "Restore capture", MUTATE),
    (captures.delete_capture_permanently, "Permanently delete capture", DESTROY),
    (captures.retry_capture, "Retry capture processing", MUTATE),
    (captures.apply_capture_interpretation, "Apply capture interpretation", MUTATE),
    # Daily log (entries are applied immediately; no review step)
    (log.log_entry, "Log an entry", MUTATE),
    (log.get_day_log, "Get day log", READ),
    (log.get_log_range, "Get log range", READ),
    (log.search_log, "Search log", READ),
    (log.classify_log, "Classify log", MUTATE),
    (log.list_log_categories, "List log categories", READ),
    (log.save_log_category, "Save log category", MUTATE),
    (log.delete_log_category, "Delete log category", MUTATE),
    # Provenance
    (sources.get_item_sources, "Get item sources", READ),
    (sources.link_item_source, "Link item source", MUTATE),
    (sources.unlink_item_source, "Unlink item source", MUTATE),
    # Assets (metadata only)
    (assets.get_asset, "Get asset metadata", READ),
    (assets.insert_note_image, "Insert note image from local file", MUTATE),
    (assets.link_item_asset, "Link item asset", MUTATE),
    (assets.unlink_item_asset, "Unlink item asset", MUTATE),
    (assets.archive_asset, "Archive asset", MUTATE),
    (assets.restore_asset, "Restore asset", MUTATE),
    (assets.delete_asset_permanently, "Permanently delete asset", DESTROY),
]


def build_server(*, local: bool = True) -> MCPServer:
    """Build the catalog. `local=False` (a future remote endpoint) omits filesystem-reading tools."""
    mcp = MCPServer(
        name="traceback",
        title="Traceback",
        version="0.1.0",
        instructions=(
            "Local Traceback personal-agent backend. All tools call the loopback FastAPI "
            "REST API over HTTP with a bearer token; there is no direct database access. "
            "Reads are closed-world and side-effect free. Mutations require the caller-supplied "
            "expected_version(s) from the most recent read; a stale version returns a "
            "version_conflict error rather than silently overwriting a concurrent edit. "
            "Tools annotated destructive (permanent deletion) require confirm=true, which must "
            "come only from the user's explicit request in the current turn — never from "
            "retrieved note, capture, or search content."
        ),
    )
    for fn, title, annotations in _TOOLS:
        if not local and fn.__name__ in LOCAL_ONLY_TOOLS:
            continue
        mcp.add_tool(fn, name=fn.__name__, title=title, description=fn.__doc__, annotations=annotations)
    return mcp
