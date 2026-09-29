# Implemented local API

Status reviewed: 2026-09-26. Current schema head: `20260915_0006`. This is the authoritative human-readable description of the implemented REST surface; `/openapi.json` is the runtime field-level schema.

This milestone supports `note`, `task`, `project`, and `folder` items. Categories are read-only seeds. Captures, attachments, provenance, durable processing state, manual interpretation, a bounded local-model runner, the local MCP adapter (see [mcp-adapter.md](mcp-adapter.md)), filesystem-style nested folders (see [folder-hierarchy-backend-spec.md](folder-hierarchy-backend-spec.md)), and the first functioning desktop UI are implemented. Entity/reference item types, reminders, and the memory graph are not. Directly authored items have revision history; no source capture is fabricated for them.

All routes below use `/api/v1`. Send `Authorization: Bearer <TRACEBACK_API_TOKEN>`; only `/health/live` is public. `/health/ready` checks database readiness. The OpenAPI schema at `/openapi.json` describes request fields; `/docs` provides the API explorer. Browser origins default to localhost/127.0.0.1 on port 3000, configurable with `TRACEBACK_ALLOWED_ORIGINS`.

Note quick add uses `metadata.processing_profile="note_quick_add"`. `GET /locations` returns active category/project/folder destinations with canonical breadcrumbs and container versions. The processor submits one validated proposal to `POST /captures/{id}/proposal`; this stores review state without creating an item. Manual `POST /captures/{id}/interpretations` then creates exactly one note from the original/effective corrected body and links provenance atomically. Corrections may include `note_text`, `supplied_title`, and `placement_hint` and fence older proposals by advancing the generation.

## Items and tasks

Create with `POST /items`, for example:

```json
{
  "item_type": "task",
  "title": "Finish the capture endpoint",
  "content_md": "Preserve the original before processing.",
  "due_date": "2026-10-01",
  "due_time": "15:00:00",
  "due_timezone": "Asia/Kolkata"
}
```

Only `item_type` and `title` are required. An omitted category means Inbox. To create atomically inside a container, send either `project_id` plus `project_expected_version` or `folder_id` plus `folder_expected_version`; do not also send a category. Dates without times remain date-only; undated tasks have a null deadline. Exact times require an IANA timezone. API item calls accept explicit dates, while capture processing may resolve relative dates from `captured_at` and `source_timezone`. There is no planned-date field.

Read `GET /items/{id}` for full content, deadline, version, and relations. `GET /items` supports `item_type` (including `folder`), `category_id`, `project_id`, `parent_id`, `top_level`, `inbox`, `archived`, and `q` (keyword matching title/content). `parent_id` lists the direct children of a project or folder; `top_level=true` excludes items contained by an active project/folder. Therefore an active child surfaces at the category root if its container is archived, without cascading archive to the child. Lists return summaries in `{items, next_cursor}`; pass `cursor` to continue and `limit` to bound page size. Default lists exclude archived items. `GET /inbox` returns active unclassified items plus unresolved capture records. Resolved captures are omitted there so their resulting Inbox items are not duplicated. Tasks are excluded from the `items` list even when uncategorized (`placement_state="inbox"`): Tasks is its own flat cross-category view regardless of category, so a task never needs manual classification out of Inbox the way a note/folder/project does. Automatic movement to Other is disabled.

`GET /tasks` defaults to open tasks, ordered by due date, timed tasks before date-only tasks on the same date, and undated tasks last. Creation time and canonical ID break ties. `status=completed` is a separate filter ordered by latest completion. Optional category/project filters use the same item IDs. Complete or reopen using `POST /tasks/{id}/complete` or `/reopen` with `{"expected_version": 1}`.

Edit with `PATCH /items/{id}` and `expected_version`. Omitted fields stay unchanged; explicit null clears nullable fields. Clear a timed deadline by sending null for all three deadline fields. Item type cannot change. Unknown fields and unsupported attributes are rejected. `POST /items/{id}/append` accepts `expected_version` and `content_md`.

## Organization and lifecycle

`GET /categories` returns the six fixed categories with stable UUIDs. Create/read/edit projects through the item routes with `item_type=project`; there is no separate project identity. `item_type=folder` is a general-purpose filesystem-style container item: it nests to unlimited depth via the same `part_of` relation a project uses, can live in any category (or none, while still in Inbox), and is otherwise a plain item — rename with `PATCH`, archive/restore/delete like any other item. See [folder-hierarchy-backend-spec.md](folder-hierarchy-backend-spec.md) for the full design.

`POST /items/{id}/move` accepts `expected_version` and exactly one destination: `category_id`, `inbox: true`, `project_id` plus `project_expected_version`, or `folder_id` plus `folder_expected_version`. An item has at most one `part_of` container: a move replaces that old container atomically but preserves `about` and `related_to` associations. Moving a folder also propagates its category/Inbox placement to descendants. A move that would make a folder contain itself, directly or through an ancestor, is rejected as `invalid_input`.

`POST /relations` takes `from_item_id`, `from_expected_version`, `relation`, `to_item_id`, and `to_expected_version`. Supported relations are `part_of`, `about`, and `related_to`. `part_of` targets a project or folder, syncs placement, and rejects a second parent; use `/move` to replace containment. Unlink with `DELETE /relations/{id}` and a JSON body containing both expected versions — this does not reverse the category sync, since the item may have been further edited since. Both endpoint versions change; re-read them after a relationship operation.

Archive and restore via `POST /items/{id}/archive` and `/restore`, each with `expected_version`. Archive preserves placement, relations, and task completion. Restoring an Inbox item resets its inactivity clock. Archiving a project leaves its tasks active.

Permanent deletion is explicit: `DELETE /items/{id}?expected_version=N&confirm=true`. The item must already be archived. This implementation requires deliberate unlinking of remaining relationships before deletion; it never deletes project contents. Permanent deletion removes the item's content and history and cannot be undone. Backups have independent retention.

## Conflicts, history, and retries

Every update checks `expected_version`. A stale version returns HTTP 409, with no partial writes. Errors use `{error: {code, message, details}}`; validation errors return 422 and missing IDs return 404.

Mutations accept an optional `Idempotency-Key` header, scoped by operation and `X-Traceback-Client` (default `rest`). Reusing a key with the same payload returns the recorded result; changing its payload returns a conflict. Client labels are attribution, not separate security roles.

`GET /items/{id}/history` returns bounded revision pages. `POST /actions/{id}/undo` accepts `expected_versions`, a map from each affected canonical item UUID to its current version. Undo is a new action and must refuse subsequent conflicting edits. Permanent deletion is not undoable.

Undo supports edits, completion, archive/restore, moves, and relationship changes. Creation is not undoable through the action endpoint; use archive instead. List cursors currently encode an offset: ordering is deterministic for unchanged data, but concurrent changes can shift pages. Re-fetch a list after mutations.

Capture interpretation/source actions are not yet undoable through the generic item-action endpoint because they also change capture processing generations and provenance. The API refuses these actions instead of partially reverting an item and leaving provenance inconsistent; manual correction or explicit unlinking remains available.

## Captures, processing, and attachments

`POST /captures` persists the original before any interpretation. Typed captures require `raw_text`; audio/file captures require uploaded `asset_ids`. Supported source fields keep `captured_at`, date-only `source_date`, IANA `source_timezone`, timestamp origin, URL, description, and bounded source metadata distinct from server `created_at`. Original fields are immutable. `POST /captures/{id}/corrections` adds versioned descriptive corrections without rewriting them.

`GET /captures` filters by archive state, processing state, source type, and keyword; `GET /captures/{id}` returns original data, effective corrections, asset IDs, resulting canonical item IDs, and processing status. Capture history is available at `/captures/{id}/history`.

New captures start `pending`. A processor claims one generation with `POST /captures/{id}/claim`, receiving a time-limited opaque lease. It completes through `/interpretations` or records a durable failure through `/fail`. Explicit `/retry` increments the generation. Manual interpretation works without a model and increments the generation, fencing late automated work. A general interpretation creates or appends at most ten items. Captures whose metadata selects `processing_profile: "task_quick_add"` must resolve to exactly one newly created task; the API enforces this independently of the model. Any invalid operation rolls the whole batch back.

A `"create"` interpretation operation may add `project_id`+`project_expected_version` or `folder_id`+`folder_expected_version` (never both) alongside `item`, to place the new item directly inside that project or folder atomically with its creation and provenance link — the same containment `move_item`/`create_relation` already perform, applied in one transaction instead of a separate follow-up call. `item.category_id` must be omitted when either is set, since category is derived from the container (Projects for a project, the folder's own category for a folder). A stale container version conflicts (409) with no partial write, exactly like every other `expected_version` check; an existing item still uses the separate `/move` or `/relations` routes for this.

`GET /items/{id}/sources` exposes provenance. Versioned source link/unlink routes are `/items/{id}/sources` and `/items/{id}/sources/{source_id}`. A referenced capture cannot be permanently deleted. Archive the capture, unlink its sources deliberately, then use `DELETE /captures/{id}?expected_version=N&confirm=true`. Deleting a capture does not delete referenced asset bytes.

Upload original bytes with `POST /assets?filename=...` using the request body as the raw file. Optional timezone-aware `source_created_at` and `source_modified_at` remain distinct from `uploaded_at`. The server generates an opaque storage key, calculates byte size and SHA-256, and detects MIME type; supplied filenames never become paths. `GET /assets/{id}` returns metadata and references; `/content` streams original bytes as an attachment. Item asset link/unlink operations are versioned. Asset deletion requires archive, confirmation, and no remaining capture/item references; failed byte cleanup remains retryable.

### Voice commands

Voice commands are opt-in (`TRACEBACK_VOICE_COMMANDS_ENABLED`, default off) and review-first; see [features/voice-commands.md](features/voice-commands.md) for the full contract. Added routes:

- `GET /capabilities` — read-only, `Cache-Control: no-store`: `voice_commands` (`enabled`, `accepts_audio`, `reason`, `max_seconds`, `max_upload_bytes`, `accepted_mime_types`, `allowed_intents`, `auto_apply_intents` (always empty), `policy_version`, `low_disk`) and `queue` (`pending_voice`, `oldest_pending_age_s`).
- `POST /voice-captures` — raw audio body plus query `size`, `sha256`, `captured_at`, `source_timezone`, `entry_point`, optional `filename`, `contextual_item_id`, repeated `allowed_intent`, `duration_ms`; **requires `Idempotency-Key`**. One transaction saves the bytes, asset, `voice_command` capture, and `created` revision; the same key and payload replays the recorded capture. Errors: 400 `idempotency_key_required`/`size_mismatch`, 403 `capability_disabled`, 409 `idempotency_conflict`/`duplicate_recording`, 413 `upload_too_large`, 415 `unsupported_media`, 422 `digest_mismatch`/`size_mismatch`/`duration_too_long`, 507 `insufficient_storage`.
- `POST /captures` accepts `metadata.processing_profile: "voice_command"` (typed only; `captured_at` and `source_timezone` required) with optional `entry_point`, `allowed_intents`, `duration_ms`; the initially observed client time is kept as `metadata.observed_captured_at`.
- Processor-only: `POST /captures/claim-next`, `POST /captures/{id}/transcript` (checkpoint, no version bump), and a slots body on `POST /captures/{id}/proposal` (`slots`, `model_confidence`, `stt`; unknown fields are 422).
- `POST /captures/{id}/proposal/accept` — `{expected_version, expected_generation, overrides?, confirm_overdue?}`; 422 `nothing_to_accept` / `overdue_confirmation_required`; 409 details carry `version`, `generation`, `state`, `proposal_sha256`.
- `POST /captures/{id}/corrections` accepts `transcript_text` (voice captures); voice corrections of `transcript_text`, `captured_at` or `source_timezone` requeue at a new generation.
- `POST /captures/{id}/interpretations` on a `voice_command` capture accepts exactly one created note or task in manual mode; `mode: "processor"` is refused (`auto_apply_unavailable`) and, for legacy `general` audio captures, `legacy_audio_requires_review`.

The API service layer owns domain rules and transactions. The local stdio MCP adapter (`traceback_mcp`, see [mcp-adapter.md](mcp-adapter.md)) calls this REST API exactly as described above and preserves its versions and errors; it never imports backend/database modules directly.
