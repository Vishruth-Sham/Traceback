# Backend spec: nested folders (filesystem-style, unlimited depth)

Status: implemented and hardened (2026-09-14), migrations `20260915_0004` and `20260915_0005`. Each item has at most one outgoing `part_of` parent (enforced by PostgreSQL); `/move` replaces that parent, direct relation creation rejects a second parent, folder placement propagates to descendants, and active children of an archived container surface at the category root. `POST /items` also accepts a project/folder plus its expected version for atomic create-in-container. See [backend-api.md](backend-api.md) for the current REST wording and [mcp-adapter.md](mcp-adapter.md) for the MCP tool catalog.

## Why

The Learning-index mockup (`initial UI views/Modern minimal UI design/Traceback Main Page (standalone).html`, artboard "6a — Learning index, ink & paper") shows a real filesystem: a category contains folders, folders contain subfolders and `.md` files, to unlimited depth, with expand/collapse. The user wants this in every category-organized section (Health & Food, Personal Growth, Books, Learning, Projects, Other) — everywhere except Tasks, which stays a flat cross-category list by design and is unaffected by this change.

The current backend (`backend/models.py`, `backend/services.py`, `backend/api.py`) has no folder concept — only 6 fixed flat categories, plus one level of containment via `item_type='project'` + a `part_of` relation, and a project is hard-forced into the `Projects` category (`move_item`'s project branch sets `item.category_id = CATEGORY_IDS["projects"]` unconditionally). That's the whole gap this spec closes.

## Key insight: reuse `project` + `part_of`, don't invent new machinery

A "folder" is structurally identical to what `project` already is: an `Item` that other items can be `part_of`. The only things that make `project` not already work as a general folder are (a) it's pinned to one category, and (b) `part_of`'s target validation hard-requires `item_type == 'project'`. Generalize both, and folders fall out almost for free — no new table, no new columns beyond nothing at all: reuse `items.category_id` (already there) and `item_relations` (already there, `relation='part_of'`).

## 1. Migration (new alembic revision, e.g. `20260915_0004_folders.py`, parent `20260914_0003`)

Only one DDL change:

```sql
ALTER TABLE items DROP CONSTRAINT ck_items_type;
ALTER TABLE items ADD CONSTRAINT ck_items_type
  CHECK (item_type IN ('note','task','project','folder','entity','reference'));
```

That's it. No new columns, no new tables. Existing rows are unaffected (default `parent`/nesting = none, i.e. no outgoing `part_of` relation).

## 2. `backend/schemas.py`

- Extend `ItemType = Literal["note", "task", "project"]` → add `"folder"`.
- `MoveRequest`: add two fields, mirroring the existing `project_id`/`project_expected_version` pair:
  ```python
  folder_id: uuid.UUID | None = None
  folder_expected_version: int | None = Field(default=None, ge=1)
  ```
  Update the `one_destination` validator to count `folder_id` as a 4th mutually exclusive choice (alongside `category_id`, `project_id`, `inbox`), and require `folder_expected_version` when `folder_id` is set (same shape as the existing `project_expected_version` requirement).
- No change needed to `ItemOut`/`RelationOut` — `item_type`/`relation` are already plain `str` on output.
- No change needed to deadline/attributes validation in `ItemCreate`/`ItemPatch` — those already key off `item_type != "task"`, so `folder` automatically gets the same "no deadline fields" treatment as `note`/`project` for free.

## 3. `backend/services.py`

**`create_relation()`** (currently line ~289):
```python
if data["relation"] == "part_of" and target.item_type != "project":
    raise DomainError("invalid_input", "part_of must target a project", 422)
```
→ change to accept folders too:
```python
if data["relation"] == "part_of" and target.item_type not in ("project", "folder"):
    raise DomainError("invalid_input", "part_of must target a project or a folder", 422)
```
Then **add cycle prevention** for folder nesting (this doesn't exist today beyond the single self-loop check at the top of the function): when `target.item_type == "folder"`, walk `target`'s outgoing `part_of` chain (`target -> its parent -> its parent's parent -> ...`) and reject if `source.id` appears anywhere in it — that would make the new relation close a loop. `move_item`'s existing project branch has an analogous single-level check (`"A project cannot contain itself"`); this generalizes it to arbitrary depth. Suggest extracting a small helper `_would_create_cycle(session, source_id, folder_id) -> bool`.

**`move_item()`** (currently ~line 326): add a new branch parallel to the existing project branch:
```python
elif data.get("folder_id"):
    folder = get_item(session, data["folder_id"], lock=True)
    require_version(folder, data["folder_expected_version"])
    if folder.item_type != "folder":
        raise DomainError("invalid_input", "folder_id must identify a folder", 422)
    if folder.id == item.id:
        raise DomainError("invalid_input", "A folder cannot contain itself", 422)
    # reuse the same cycle check as create_relation when item.item_type == "folder"
    before_folder = item_snapshot(session, folder)
    item.category_id = folder.category_id   # inherit placement from the containing folder
    item.placement_state = "classified"
    item.inbox_entered_at = None
    existing = session.scalar(select(ItemRelation).where(
        ItemRelation.from_item_id == item.id, ItemRelation.relation == "part_of", ItemRelation.to_item_id == folder.id))
    if not existing:
        session.add(ItemRelation(from_item_id=item.id, relation="part_of", to_item_id=folder.id))
        session.flush()
    bump(folder)
    record_revision(session, action, folder, before_folder)
```
This is a copy-paste of the existing project branch with `project` → `folder` and `CATEGORY_IDS["projects"]` → `folder.category_id` (the one substantive difference: a folder's category is whatever category it was created in, not forced to one fixed value).

**Nothing else needs to change.** In particular:
- `permanently_delete()` already blocks deletion of any item that still has *any* relation pointing at or from it (`"Unlink the item before permanently deleting it"`). A non-empty folder has children with `part_of` relations pointing at it, so **deleting a non-empty folder is already correctly blocked with zero new code**.
- `set_archived()` has no cascade logic today, and none should be added — archiving a folder must not archive its contents, exactly like archiving a project today leaves its tasks active. This falls out for free.
- Renaming a folder is just `PATCH /items/{id}` with `title`, already generic — no change.

## 4. `backend/api.py`

- `list_items()`: extend the query param `item_type: Literal["note", "task", "project"] | None` → add `"folder"`.
- Add an optional `parent_id: uuid.UUID | None` query param that does the same join `project_id` already does, but generically:
  ```python
  if parent_id:
      stmt = stmt.join(ItemRelation, and_(ItemRelation.from_item_id == Item.id, ItemRelation.relation == "part_of")).where(ItemRelation.to_item_id == parent_id)
  ```
  This lists the direct children of a folder *or* a project with one param — recommend keeping `project_id` working exactly as it does today (used by the existing frontend's project-detail page) and adding `parent_id` as the new, folder-capable filter, so no simultaneous frontend change is forced.
- Add an optional `top_level: bool = False` query param, combinable with `category_id`, that filters to items with no outgoing `part_of` relation to an **active** container. This prevents an active child from disappearing when its parent is archived:
  ```python
  if top_level:
      contained = select(ItemRelation.from_item_id).where(ItemRelation.relation == "part_of")
      stmt = stmt.where(Item.id.not_in(contained))
  ```
- No new endpoint is required. Folder creation is `POST /items` with `item_type: "folder"`; it can include `folder_id` and `folder_expected_version` to create and nest atomically. Existing items relocate through `POST /items/{id}/move`. Direct `POST /relations` with `relation: "part_of"` is supported for initially uncontained items, but rejects a second parent and directs callers to `/move`.

## 5. Resolved: `/relations` now inherits category exactly like `/move` (2026-09-15)

The original draft of this spec proposed keeping `POST /relations`'s existing asymmetry (it didn't sync `category_id` on `part_of`, only `/move` did) and flagged deciding whether folder nesting should hard-enforce category consistency instead. Product decision: **inherit, don't just validate** — an item's category must never depend on which of the two routes was used to nest it. Implemented as a shared `_place_in_container(item, container)` helper in `backend/services.py`, called from both `move_item()` and `create_relation()`'s `part_of` branch: containment inside a project always means the Projects category; containment inside a folder inherits whatever category the folder itself currently has, including staying in Inbox if the folder is itself still unclassified. This also fixes a pre-existing, unrelated inconsistency: previously only `/move` forced project membership into the Projects category, while `/relations` left a project-linked item's category untouched entirely.

## 6. `traceback_mcp`

The MCP adapter calls this same REST API and mirrors its schemas in tool definitions — whatever tool currently exposes `item_type` (for creating items) and the move/relation operations needs its enum/description updated to include `"folder"` and the new `folder_id` move destination. No protocol-level change, just keeping the tool schema in sync with the REST contract above.

## 7. Tests to add (`tests/`)

- Create a folder (`item_type: "folder"`), read it back.
- Nest folders 2–3 levels deep via `/relations` `part_of`; list a folder's children via `parent_id`.
- Move a note into a folder via the new `/move` `folder_id` branch; confirm `category_id` inherited from the folder.
- Attempt to create a cycle (`A part_of B`, then `B part_of A`) → expect rejection.
- Attempt to permanently delete a non-empty folder → expect the existing `linked_item_conflict` 409 (regression-style test confirming the free behavior actually holds).
- Archive a folder with children → children remain active and still listable by `parent_id`.
- `GET /items?category_id=<learning>&top_level=true` returns only root-level folders/items in that category.

## Summary of the diff surface

| File | Change |
|---|---|
| `migrations/versions/2026091X_000X_folders.py` (new) | One `CHECK` constraint update, nothing else |
| `backend/schemas.py` | Add `"folder"` to `ItemType`; add `folder_id`/`folder_expected_version` to `MoveRequest` + validator |
| `backend/services.py` | `create_relation()`: allow `part_of` → folder target + cycle check. `move_item()`: new `folder_id` branch (copy of the project branch, category inherited instead of forced) |
| `backend/api.py` | `list_items()`: allow `item_type=folder`; add `parent_id` and `top_level` query params |
| `traceback_mcp/...` | Update tool schema enums/descriptions to match |
| `tests/...` | New cases per §7 |

Everything else (archive, restore, permanent-delete conflict, revision history, undo, `PATCH` for rename) already works unmodified because folders are plain `Item` rows.
