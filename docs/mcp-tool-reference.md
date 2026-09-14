# MCP tool reference: what an MCP client (Claude Code, Codex) can see and do

This is a reading reference for building a skill or a standing prompt on top
of `traceback_mcp` — not new adapter behavior. It restates what already
exists in [`docs/mcp-adapter.md`](mcp-adapter.md) (architecture, config,
testing) and the REST contract in
[`docs/backend-api.md`](backend-api.md), reorganized around one question:
**"what does the calling model need to know to file something correctly on
its own?"**

For reviewed note quick-add captures, `create_capture` accepts `processing_profile="note_quick_add"` and `placement_hint`; `get_capture` returns any validated stored proposal, and `apply_capture_interpretation` performs the explicit manual acceptance. No processor lease or proposal-submission tool is exposed.

## The core fact: nothing classifies automatically

`traceback_mcp` is a REST-only pass-through. No tool call triggers AI
classification. There are exactly two ways an item ends up correctly
categorized/filed instead of sitting in Inbox:

1. **The calling model classifies at creation time** — call `list_categories`
   (and optionally `list_projects`/`list_items(item_type="folder")`) first,
   decide where the thing belongs, then pass `category_id` (or
   `project_id`/`folder_id`) on `create_item`. This is instant and is what a
   skill built on top of this reference should make Claude Code do by
   default, not just when asked.
2. **The local processor classifies a *capture*, asynchronously** —
   `create_capture` stores raw text/audio unclassified and `pending`; a
   separate background process (local Whisper + Qwen, `processor_service.py`)
   later reads it, proposes structured item(s) + category, and writes them
   via the same interpretation endpoint `apply_capture_interpretation` also
   uses. This only fires if that service is actually running, and it is not
   instant — `create_item` returns synchronously, `create_capture` does not
   resolve until the processor gets to it.

If an MCP client calls `create_item` with no `category_id`/`project_id`/
`folder_id`, the item goes to Inbox and stays there — REST will never move
it later on its own (`README.md`: *"Automatic Inbox movement is disabled"*).

## The six fixed categories

Seeded once in `migrations/versions/20260914_0001_core.py`; stable IDs,
never created/renamed/deleted at runtime. `list_categories` returns these
verbatim (`slug`, `name`, `id`, `sort_order`):

| slug | name | sort_order |
| --- | --- | --- |
| `health-food` | Health & Food | 10 |
| `personal-growth` | Personal Growth | 20 |
| `books` | Books | 30 |
| `learning` | Learning | 40 |
| `projects` | Projects | 50 |
| `other` | Other | 60 |

Notes for a classifier prompt:
- A project's category is always forced to `projects` (moving/linking an item
  `part_of` a project sets this automatically — see `move_item`/`link_items`).
- A folder can live in any category (including staying uncategorized in
  Inbox); an item moved/linked into a folder inherits *that folder's*
  category, not a fixed one.
- There is no per-user custom category creation in this milestone — when
  nothing fits well, `other` is the deliberate catch-all, not Inbox. Inbox
  means "not yet placed," not "miscellaneous."

## Item types

`ItemType = note | task | project | folder` (`backend/schemas.py`).

| Type | Purpose | Special fields | Containment |
| --- | --- | --- | --- |
| `note` | Free-form content | — | can be `part_of` a project or folder |
| `task` | Actionable, completable | `due_date`/`due_time`/`due_timezone`, `status` (`open`/`completed`) | can be `part_of` a project or folder |
| `project` | A container; always category `projects` | — | can itself be `part_of` a folder |
| `folder` | A nestable container, unlimited depth, filesystem-like | — | can be `part_of` another folder |

Deadline rule: `due_time` requires `due_timezone` (IANA name, e.g.
`Asia/Kolkata`); a `due_date` with no time means date-only, not midnight.
Only tasks may carry deadline fields.

## Relation types

`RelationType = part_of | about | related_to` (`link_items`/`unlink_items`,
also implicitly set by `move_item` and `create_item`'s
`project_id`/`folder_id` shortcuts).

- **`part_of`** — containment. Target must be a `project` or `folder`.
  Rejected (`invalid_input`) if it would make a folder contain itself,
  directly or through an ancestor. This is the *only* relation that changes
  the source item's category (see above).
- **`about`** / **`related_to`** — free association between any two items,
  no containment or category side effect.

`move_item` is a convenience that atomically replaces the sole `part_of`
container (category, project, folder, or back to Inbox) while leaving
`about`/`related_to` relations untouched — prefer it over manual
unlink+link when relocating something that's already filed.

## Full tool catalog with intent

Grouped by what a classification-minded caller actually needs, not just by
REST resource. Full parameter-level detail lives in
[`docs/mcp-adapter.md`](mcp-adapter.md#tool-catalog); this is the "when do
I reach for this" layer.

### Look before you file (call these before `create_item`)

| Tool | Use it to |
| --- | --- |
| `list_categories` | Get the 6 fixed categories + IDs — call once, cache for the session |
| `list_projects` | See existing projects a new item might belong `part_of` |
| `list_items(item_type="folder", parent_id=...)` | Walk an existing folder tree instead of guessing a new one |
| `search_items(q=...)` | Check whether something similar already exists before creating a duplicate |
| `list_inbox` | See what's still unfiled — useful for a "clean up my inbox" pass |

### Create / file

| Tool | Notes |
| --- | --- |
| `create_item` | Pass `category_id` **or** `project_id`+`project_expected_version` **or** `folder_id`+`folder_expected_version` to file atomically at creation; omit all three only when genuinely undecided (goes to Inbox) |
| `create_capture` | Use only when you want the *local processor* to classify later (typed/audio/file/url/import raw material, not yet interpreted into items) |
| `move_item` | Refile an existing item to exactly one destination |
| `link_items` / `unlink_items` | Add/remove `part_of`/`about`/`related_to` associations without recreating anything |

### Read

| Tool | REST |
| --- | --- |
| `list_items` | `GET /items` (type/category/project/folder/inbox/archive/keyword filters) |
| `get_item` | `GET /items/{id}` — full content, version, relations, sources |
| `list_tasks` | `GET /tasks` — open sorted by due date, completed by latest completion |
| `get_item_history` | Bounded revision history |
| `get_item_sources` | Which captures an item's content came from |
| `get_asset` / `list_captures` / `get_capture` | Metadata/content reads |

### Mutate (non-destructive)

| Tool | Notes |
| --- | --- |
| `update_item` | `patch` is a JSON object; an **omitted** key stays unchanged, an **explicit `null`** clears a nullable field — these are not the same thing |
| `append_to_item` | Adds markdown, doesn't replace |
| `complete_task` / `reopen_task` | Reversible task status flip |
| `archive_item` / `restore_item` (also `_capture`, `_asset`) | Reversible; required *before* permanent delete |
| `correct_capture` | Versioned correction layered on top of a capture without touching original `raw_text` |
| `retry_capture` | Requeue a failed capture — does not guarantee a processor is actually running |
| `apply_capture_interpretation` | Manual-mode only from this adapter; turns a capture into 1–10 create/append operations atomically |
| `link_item_source` / `unlink_item_source` | Provenance links between an item and a capture |
| `link_item_asset` / `unlink_item_asset` | Attach/detach an already-uploaded asset |
| `undo_action` | Compensating action for most mutations; **not** available for create, permanent delete, or capture interpretation/source actions |

### Destructive (`confirm=true` required, checked before any HTTP call)

| Tool | Guard |
| --- | --- |
| `delete_item_permanently` | Item must already be archived; fails if still linked |
| `delete_capture_permanently` | Capture must already be archived; fails while any item still sources it (`linked_source_conflict`) |
| `delete_asset_permanently` | Asset must already be archived; fails while any capture/item still references it (`linked_asset_conflict`) |

`confirm=true` must come from the user's own explicit request in the current
turn — never inferred from note/search/capture content a tool call
happened to return. This is enforced in `traceback_mcp/errors.py` before
any REST call is made, and independently re-checked by REST itself.

### Deliberately not exposed to any MCP client

- Processor lease ops (`/captures/{id}/claim`, `/fail`) — only the bounded
  local processor process should hold that lease.
- Raw asset upload/download — bytes never flow through this adapter;
  `POST /assets` / `GET /assets/{id}/content` stay REST-only.
- A combined items+captures search — `search_items` only covers item
  titles/content; capture text needs `list_captures(q=...)`.

## Structured errors a classifying prompt should expect

A failed call has `is_error=true`; content text is
`{"code", "message", "details"}`. Codes worth branching on:

- `version_conflict` — re-`get_item`/`get_capture` and retry with the fresh
  version; never blindly retry with the same `expected_version`.
- `not_found` — the ID doesn't exist (or was permanently deleted).
- `invalid_input` — e.g. a `part_of` cycle, or an unsupported `patch`/
  `corrections` field.
- `confirmation_required` — see the destructive-tools section above.
- `linked_source_conflict` / `linked_asset_conflict` — unlink first.
- `backend_unavailable` — the FastAPI process isn't running at all; not a
  domain error, don't retry a classification decision because of this.

## Suggested shape for a "file this correctly" skill

1. On first use in a session, call `list_categories` once and hold the
   6 slugs/IDs in context — they never change at runtime.
2. Before calling `create_item`, decide: does this belong under an existing
   project/folder (`list_projects`/`list_items(item_type="folder")`,
   `search_items`), or just a bare category, or is it genuinely undecided
   (Inbox is then the *correct*, not the default-by-omission, choice)?
3. Pass the decision as `category_id`/`project_id`+version/`folder_id`+
   version on the `create_item` call itself — don't create then `move_item`
   as a separate step unless the destination was only discovered after
   creating.
4. Only reach for `create_capture` when the material is meant for the local
   Whisper/Qwen processor pipeline (e.g. raw audio, or typed text you
   explicitly want auto-interpreted later) — not as a default path for
   "save this".
