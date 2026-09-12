# Traceback — First Local Backend Plan

Date: 2026-09-12  
Status: Planning specification; no backend, database, or client configuration has been created.

This document is the current backend plan. Latest user decisions take precedence over the original handoffs and earlier UI mockups. Detailed schema and API choices below are proposals for implementation, not claims that they already exist.

## Confirmed scope

- One user/admin, on their PC. Local first; hosted deployment comes later.
- Local PostgreSQL, local attachment storage, a REST API, and local MCP access. Supabase is a later hosting option, not a first-version dependency.
- Capture processing will use local Whisper plus Qwen3.5-4B on the user's base M5 MacBook Air. Runtime defaults below are proposed pending on-device validation; no models have been installed or benchmarked.
- One canonical item ID across category/project pages, Tasks, REST, and MCP.
- Manual control is mandatory for every implemented content type and its user-editable fields. REST must support direct creation, editing, organization, relationships, completion, and archive/deletion without requiring an AI interpretation or MCP client.
- Tasks is the only task view. No Today page, Today endpoint, or planned-date field.
- One optional due date: “do tomorrow” and “finish by tomorrow” mean the same thing.
- Open tasks sort by due date, overdue first, then upcoming, then undated. Completed tasks have their own filter.
- Unclassified items go to Inbox, can be moved manually, and eventually move to Other after inactivity. The interval is not yet chosen.
- Archive first, permanent deletion from Archive. Task completion and archiving are separate operations.
- Keep Skills as the user's admin surface and record of desired capabilities. Its existence does not require every skill to be implemented in the first backend slice.

## 0. Data model and definitions

### Categories, items, and views

Seed fixed categories with stable IDs/slugs: Health & Food, Personal Growth, Books, Learning, Projects, Other. Other replaces Everyday Life per the explicit removal decision; its later appearance in a recap is not treated as a confirmed reversal.

A category is a broad area. An item is an actual thing: a note, task, project, book, recipe, etc. Projects is a category; Traceback is a project item. Categories do not each need separate databases or service implementations.

Inbox is unresolved placement. Tasks is a query over task items. Archive is a query over archived items. These views do not contain copies of objects.

Each item has one primary category or no category while unclassified. Relationships express overlap: a Personal Growth quote can link to a book; a Learning task can link to a project. Reading a project includes linked active items even when their primary categories differ.

### Proposed tables

| Table | Fields and meaning |
| --- | --- |
| `categories` | `id`, stable `slug`, `name`, `sort_order`; seeded, read-only through first-version APIs |
| `captures` | `id`, `source_type`, original `raw_text`, original `description`, `url`, source/client context, `captured_at`, `created_at`, `archived_at` |
| `assets` | `id`, storage key, original filename, extension, declared/detected MIME type, byte size, SHA-256 checksum, upload state, `uploaded_at`, nullable source-created/source-modified times, validated media metadata; no machine-specific absolute paths in domain records |
| `capture_assets` | Capture/asset links; supports several attachments per capture |
| `items` | `id`, `type`, `title`, `content_md`, nullable `category_id`, `placement_state`, validated `attributes`, `version`, `created_at`, `updated_at`, `archived_at`, `inbox_entered_at`, `last_user_action_at` |
| `task_details` | `item_id` as primary/foreign key, `status` (`open` or `completed`), nullable `due_date`, nullable `due_time`, `due_timezone`, nullable `completed_at` |
| `item_relations` | `id`, `from_item_id`, `relation` (`part_of`, `about`, `related_to` initially), `to_item_id`; unique relation tuple, no self-links |
| `item_sources` | `item_id`, `capture_id`, optional `action_id`; explicit provenance for every interpreted type |
| `item_assets` | Links assets to items without duplicating bytes |
| `actions` | `id`, actor (`user`, `mcp`, `processor`, `system`), client label, request/idempotency key, timestamps, undo linkage |
| `item_revisions` | Action ID, item ID, resulting version, before/after snapshots covering item details and changed relationships/sources |
| `capture_processing` | One current row per capture: processing state, derived transcript/result, attempt count, retry timing, lease, error, processing generation |
| `settings` | User timezone (initially Asia/Kolkata), optional Inbox inactivity threshold; no settings UI required initially |

Use UUIDs for public identifiers. Task ID is the item ID, not a second identity. Storage keys remain stable if assets later move to object storage.

Maintain capture content separately from derived processing fields. A direct UI-created item can have user-authored revisions without an invented source capture; an agent interpreting supplied content must preserve it as a capture and link resulting items.

### File, time and source metadata

Metadata is a first-backend requirement, not something deferred to the future memory graph. Store frequently filtered timestamps in typed columns and optional format-specific details in validated metadata. Return useful metadata through REST/MCP and show it in a UI details panel.

| Record | Metadata to preserve |
| --- | --- |
| Capture | `captured_at` (user/source capture event), `created_at` (server receipt), source timezone/offset when available, timestamp origin/precision, source type, client/app identifier, original URL, optional external source ID and contextual project/item ID |
| Asset | Original filename/extension, declared and detected MIME type, actual size, SHA-256, stable storage key, server `uploaded_at`, nullable `source_created_at` and `source_modified_at`, origin of supplied timestamps, upload state |
| Audio/image/document | Audio duration and codec; image pixel dimensions/orientation; document page count when inexpensive to read. Extracted fields may be unavailable; do not require OCR or model analysis merely to save an asset. |
| Item | Server `created_at` and `updated_at`, content revision, archived/completed times where applicable, actor/client attribution through actions; source links preserve original time context |
| Processing run | Queued/start/finish times, source version/checksum, model identifier/digest, runtime/extractor/prompt version, attempt and error state |
| Web/reference | Original and normalized URL, supplied title/author/publication time when known, source of each supplied value; `retrieved_at` only if a fetch actually occurs |

Time rules:

- Store known instants as timezone-aware timestamps, normalized to UTC. Preserve the source timezone/offset separately when known; render in the user's selected timezone, initially Asia/Kolkata.
- Capture time, source-file creation time, upload time, note edit time, and the event described in the content are different. Do not substitute one for another.
- Date-only or approximate source dates need precision metadata (and date/range fields when appropriate); do not invent an exact midnight timestamp. Task date-only semantics remain as defined below.
- Original file creation/modification times may be unavailable in browser uploads. Preserve available values and leave unknowns null; server upload time is always available. Record client-supplied timestamps as such rather than treating them as verified server facts.
- Backfilled captures can have old `captured_at` but recent `created_at`. Relative-date interpretation uses the capture's reliable event/timezone context; ask/review if that context is missing or contradictory.
- Changing placement must not change original capture/file times. Updating item metadata changes `updated_at` and creates a revision, but must not pretend the note's content was newly authored.
- Explicitly described events (for example, a visit last month) receive their own date/context; future memory validity is derived from that evidence, not from upload time.

Metadata rules:

- Compute actual byte size/checksum and detected type server-side. Do not use an original filename as a storage path. Preserve original bytes even if a derived preview/transcription changes format.
- Reuse identical bytes if desired, but never merge distinct capture events simply because their attachments share a checksum.
- Preserve corrections to descriptive/source metadata with history while keeping observed technical metadata and original input intact.
- Avoid indiscriminately indexing embedded EXIF/GPS, local filesystem paths, device identifiers, or other unrelated metadata. Keep extracted fields explicitly scoped; future external visibility rules apply to metadata and history as well as content.
- Metadata can be added asynchronously after persistence. Missing optional metadata must not block capture success; expose extraction state where relevant.

Acceptance: save a file with an old modification time and verify it remains distinct from today's upload time; ingest a backdated capture; preserve a date-only source date; handle missing timestamps; retrieve provenance and timestamps through UI/REST/MCP; verify edits/moves do not rewrite original times. Backups/exports retain metadata alongside IDs and original assets.

### Item types and scope

Manual operations are a release requirement for each supported type. When a later feature adds recipes, food entries, goals, or another structured type, its manual fields and CRUD must ship with it. Fixed top-level categories remain seeded per the existing decision; manual control includes choosing categories and managing their contents, not automatically introducing editable system categories.

Start executable CRUD with `note`, `task`, `project`, `entity`, and `reference`. A book is an entity with `entity_type=book`; project stays an explicit item type. Note/task/project behavior is the first acceptance slice, not a requirement to finish every category-specific feature.

Use versioned, validated attributes for entity details such as author, genre, and reading status. Define fields for recipes, food entries, goals, and list entries before implementing those features. Do not silently treat a food log or recipe as an unstructured note and claim tracking is complete. Checkable shopping entries can start as tasks associated with a list/entity; a reusable list UI is later work.

### Invariants

- `placement_state=inbox` implies `category_id` is null; `classified` implies a valid category.
- Moving to a project sets the category to Projects and adds its `part_of` relation in one operation. Additional cross-category associations use explicit links rather than silent category changes.
- Project membership through `part_of` targets a project for the first version. Do not introduce arbitrary recursive folder containment yet.
- `task_details` exists exactly for task items. Task completion requires `completed_at`; reopening clears it. Type changes are not allowed through generic PATCH initially.
- Archived is independent of placement and completion. Archiving a completed task preserves completion; restoring it does not reopen it.
- Writes, task details, provenance, revisions, and relationship changes commit atomically through the shared service layer.
- Every update uses `expected_version`. Conflicting versions produce a conflict, never silent last-write-wins behavior.
- Actions affecting several items lock/check versions and commit together. Undo is a new compensating action and refuses conflicting subsequent edits.
- User input, saved notes, and sources are data; a retrieved instruction cannot bypass tool validation or authorize destructive operations.

### Task date semantics

There is one conceptual deadline, not separate planning and due dates. Preserve whether the user gave a date only or an exact time: `due_date` plus optional `due_time` and timezone. An absent time does not mean midnight.

Resolve relative dates against the capture timestamp and user timezone, not the time a delayed worker eventually processes it. Return the normalized deadline to the caller. A date-only task becomes overdue after that local calendar day ends; a timed task after its deadline.

Sort open tasks by due date ascending with null dates last; on the same day timed tasks precede date-only tasks. Use creation time and ID as stable tie-breakers. Overdue is derived, not a separately stored status. Completion never deletes a task.

### Capture and Inbox behavior

1. Persist the raw capture and a durable pending processing row before returning success.
2. A local worker transcribes voice with Whisper, then sends the transcript (or typed text directly) to Qwen3.5-4B. Its agent runner calls controlled MCP tools to search and apply an interpretation. Codex/Claude Code remain alternative clients, not prerequisites for capture processing. Manual CRUD works without any model running.
3. An interpretation is one atomic batch: create/update items, attach sources, record revisions, and mark processing resolved. Repeated calls with the same idempotency key return the same result. Distinct reprocessing requires a new generation and explicit intent.
4. If classification is uncertain, create a source-linked Inbox item. If extraction itself is pending or fails, show the capture's processing row in Inbox with its state.
5. Avoid duplicate Inbox cards: processing captures are listed only while unresolved; once interpreted, list only unclassified resulting items.
6. “Move to…” routes an Inbox item to a category or project. Moving the classification does not complete a task or remove its deadline.
7. Automatic Other placement applies only to unclassified, unarchived items after the configured inactivity interval. Failed or pending captures stay visible and retryable.
8. Proposed inactivity anchor: the later of Inbox entry and last explicit edit/review. Background jobs and merely listing/opening items do not reset it. Until the interval is chosen, cleanup remains disabled.
9. Cleanup rechecks eligibility transactionally, records an undoable action, and never overrides a concurrent manual move. It catches up on next startup if the PC was asleep.

The UI can manually resolve a pending or failed capture through the same atomic interpretation operation: create a note/task or attach content to an existing item, choose its destination, and preserve source links. Successful manual resolution invalidates the pending processing generation so a delayed worker cannot duplicate or overwrite the user's result. The original recording/text remains preserved; transcript or source-context corrections are stored as revisions/annotations rather than destructive edits to the original.

### Archive, restore, and permanent deletion

Archive hides an item from default lists/search but preserves ID, sources, relations, completion state, and history. Archive listing is explicit. Restore keeps the same ID; proposed behavior for restored Inbox items is to reset their inactivity clock so they do not immediately disappear again.

Archiving a project affects only the project. Its tasks stay in Tasks; context can label their project as archived. Do not cascade archive or deletion through related items.

Permanent deletion requires an archived item, its current version, and explicit confirmation. Delete the item and its task details, source links, relations, and item-content revision snapshots. Keep at most a content-free deletion event; undo cannot restore a permanently deleted item. For grouped action logs, remove that item's snapshots and mark any affected group as no longer fully undoable.

Deleting an interpreted item does not delete a shared original capture or recording. Separate archive/delete operations for captures must show source usage and block permanent deletion while remaining items reference the capture. Asset deletion is reference-aware; remove bytes only after all capture/item references are gone. Queue failed byte cleanup for retry rather than pretend it succeeded. Backups have their own retention and are not retroactively erased by deleting live records.

## 1. Local persistence and runtime

Proposed stack: FastAPI with a small shared Python service layer, PostgreSQL, SQLAlchemy/Alembic for models/migrations, and local files under a configured data directory. Confirm compatible package versions during implementation. Use one local PostgreSQL instance, preferably an existing installation; otherwise a small container with a persistent volume. Do not require the full local Supabase stack.

```text
PC browser ── REST ───────────────────┐
                                     ▼
Codex / Claude Code → stdio MCP → Local FastAPI → PostgreSQL
                                     │
                                     └────────→ Local asset directory
```

The API is the single writer. Each MCP client may launch its own thin stdio adapter, but all call the same API and database. The API must be running for those adapters to work; return a useful unavailable error when it is stopped.

Bind the API and database to loopback for this stage. Use a local bearer credential for API clients, including the MCP adapter, and restrict browser origins. No signup system, account billing, roles UI, or hosted OAuth is required. Before remote exposure, add proper hosted authentication and authorization. Local storage does not imply model inference is offline: content sent through Codex/Claude or a later hosted AI provider may leave the PC.

Upload through the API, using opaque asset IDs. Persist bytes before confirming a media capture, and reconcile abandoned uploads. Do not let the MCP server accept arbitrary filesystem paths as if they were asset IDs. A later file-import tool must have explicit access boundaries.

Provide one documented start/stop procedure, migrations, health/readiness checks, and backup/restore for both PostgreSQL and assets. Verify a restore into a separate local database/data directory before depending on the app for daily use.

### Local capture models: proposed first configuration

- Hardware target: base M5 MacBook Air, assumed 16GB unified memory from [Apple specifications](https://www.apple.com/macbook-air/specs/). Confirm available memory during setup, including other applications.
- Speech: Whisper `small` multilingual through [whisper.cpp](https://github.com/ggml-org/whisper.cpp), which supports Apple Silicon/Metal. Benchmark `base` if latency or memory pressure is excessive; choose based on the user's own recordings, technical terms, and mixed-language speech.
- Interpretation: Ollama `qwen3.5:4b`, currently a Q4_K_M package listed at 3.4GB in the [Ollama registry](https://ollama.com/library/qwen3.5:4b). Download size is not total runtime memory. Pin the tested model digest/runtime version during implementation.
- Start with a 4K–8K context budget, bounded output, one active capture job, and sequential transcription then interpretation. Keep retrieved snippets and tool schemas compact. Do not load the entire memory store into context. Release idle models if memory pressure requires it.
- Prefer non-thinking mode for routine extraction if supported by the installed model/runtime; verify the actual behavior and accuracy. Do not promise a throughput or end-to-end latency before measuring this machine.
- The worker hosts a small agent runner: it sends tool schemas to the local model, executes validated requests through a local MCP client/adapter, and feeds results back. Ollama/model inference alone is not an MCP client. All mutations still go through the shared API.
- Start with list/search/read and atomic `apply_capture_interpretation`; exclude permanent deletion from automatic capture processing. Limit tool rounds, validate IDs and dates, and send ambiguous/invalid outputs to Inbox. A model's self-reported confidence is not sufficient evidence of correctness.
- Audio is persisted before transcription; text skips Whisper. Neither model needs Codex/Claude Code open. Local processing must not silently fall back to a hosted model. Once dependencies/weights are installed, verify capture processing with network access disabled.
- Evaluation: use 20–30 representative text/voice captures, including dates, technical vocabulary, duplicate project names, multiple tasks, uncertain routing, and manual edits during processing. Measure transcription errors, action/target/date correctness, warm/cold latency, and peak memory/swap. Verify manual save/edit during model failure and retries without duplicate writes.

### Hosted migration

Keep SQL schema provider-independent, attachments behind a small storage interface, and domain IDs independent of local paths or auth providers. Later migration can move Postgres to Supabase/another host, copy assets to private object storage, add hosted auth, and point the API at those services. It is a migration with verification, not merely changing a URL: preserve IDs, verify row/asset counts and checksums, test access control, and retain a rollback backup.

## 2. REST API and MCP contract

Use `/api/v1` for REST. API and MCP validation, errors, and business rules are shared; MCP wraps HTTP calls and does not write to the database directly. All endpoints below are proposed contracts.

| Purpose | REST | MCP |
| --- | --- | --- |
| Categories | `GET /categories` | `list_categories` |
| Item discovery | `GET /items` with category/type/query/project/entity/archive filters | `list_items` |
| Projects convenience | `GET /items?type=project` | `list_projects` wrapping the same query |
| Read item and details | `GET /items/{id}` | `get_item` |
| Create item | `POST /items` | `create_item` |
| Edit item | `PATCH /items/{id}` | `update_item` |
| Append note content | `POST /items/{id}/append` | `append_to_item` |
| Move to category/project | `POST /items/{id}/move` | `move_item` |
| Add/remove association | `POST /relations`, `DELETE /relations/{id}` | `link_items`, `unlink_items` |
| Tasks | `GET /tasks?status=open` with optional category/project filters | `list_tasks` |
| Complete/reopen | `POST /tasks/{id}/complete`, `POST /tasks/{id}/reopen` | `complete_task`, `reopen_task` |
| Save original | `POST /captures` | `create_capture` |
| Read original/status | `GET /captures/{id}` | `get_capture` |
| Recent captures | `GET /captures` | `list_captures` |
| Upload/read asset | `POST /assets`, `GET /assets/{id}/content` | Asset IDs used in tools; raw binary upload handled through REST initially |
| Apply extracted changes | `POST /captures/{id}/interpretations` | `apply_capture_interpretation` |
| Retry failed processing | `POST /captures/{id}/retry` | `retry_capture` (requeues; does not guarantee a processor is running) |
| Inbox | `GET /inbox` | `list_inbox` |
| Search | `GET /search` with type/category/scope filters | `search_items` |
| Source inspection | `GET /items/{id}/sources` | `get_item_sources` |
| History | `GET /items/{id}/history` | `get_item_history` |
| Undo | `POST /actions/{id}/undo` | `undo_action` |
| Archive/restore item | `POST /items/{id}/archive`, `POST /items/{id}/restore` | `archive_item`, `restore_item` |
| Archive listing | `GET /items?archived=true` | `list_items(archived=true)` |
| Permanent item deletion | `DELETE /items/{id}` with confirmation and version | `delete_item_permanently` |
| Archive/restore capture | `POST /captures/{id}/archive`, `POST /captures/{id}/restore` | `archive_capture`, `restore_capture` |
| Permanent capture deletion | `DELETE /captures/{id}` with confirmation, usage checks | `delete_capture_permanently` |

Transport metadata must distinguish reads, reversible mutations, and destructive actions. Explicit deletion confirmation must originate from user intent; tool labels or instructions inside retrieved content are not confirmation. Keep the first local tool catalog practical; convenience wrappers can be added after core operations work.

### Contract rules

- Cursor pagination and bounded page size for lists, search, and history. Return summaries in lists; fetch full item content by ID.
- Create returns the canonical ID/version; updates return the resulting version/action ID. Never return a second “task view ID.”
- Mutations support idempotency keys scoped to operation/caller, with request-body hashes: same key and payload returns the prior result, changed payload conflicts.
- Capture success means persisted, not interpreted. Return `capture_id`, state, and asset IDs; later reads expose resulting item IDs.
- PATCH distinguishes omitted fields (unchanged) from explicit null (clear, if allowed). Reject unknown fields/type-invalid attributes.
- Direct user actions do not require model availability, classification confidence, or fabricated captures. Source-derived edits retain provenance. All manual actions use the same versions/history as MCP writes, and stale automated actions must conflict with newer manual edits.
- Default lists exclude archived items. Tasks defaults to open; completed is explicit. General memory search excludes completed operational items unless requested.
- Keyword search starts over titles and content, with explicit source-capture search available. Do not hide originals behind semantic search only.
- Structured errors include a stable code, message, and relevant details: invalid input, not found, version conflict, invalid transition, linked-source conflict, or service unavailable. REST maps these to appropriate HTTP statuses; MCP preserves the same domain error codes.
- Date interpretation belongs before mutation; tools accept explicit normalized date/time fields. Retain the originating text and timezone context in captures.

### Example integration acceptance flow

1. Codex saves: “For Traceback, finish the capture endpoint tomorrow.” Receives capture ID `c1`.
2. It lists Projects, selects the Traceback project by ID, and submits a task interpretation for `c1`.
3. API creates one task `t1`, source link, project relation, and action history atomically.
4. UI Tasks and the Traceback project both show `t1` with the same due date.
5. Claude Code reads and completes `t1`; UI reflects completion on refresh/poll.
6. A repeated request does not duplicate work; a stale edit conflicts.
7. Archive hides `t1`; restore preserves its completed state. Confirmed permanent deletion from Archive removes the item without deleting unrelated project content or the shared capture.

Local stdio support is documented by [OpenAI for Codex](https://developers.openai.com/codex/mcp/) and [Anthropic for Claude Code](https://code.claude.com/docs/en/mcp#option-3-add-a-local-stdio-server). Actual tool discovery and calls in both installed clients remain implementation acceptance checks; no client configurations have been changed during planning.

## Build sequence and completion criteria

1. **Definitions/schema:** finalize core constraints, create migrations and fixed category seeds. Verify fresh initialization and invariant failures using real PostgreSQL.
2. **Local persistence and REST:** implement item/task/project CRUD, dates, relations, archive/restore, conflict handling, and backup/restore. Verify shared IDs, ordering, completed filtering, and non-cascading project actions.
3. **Capture and provenance:** add raw capture/media storage, atomic interpretation, revisions/undo, Inbox and manual routing. Test failed uploads, retries, conflicts, and durable pending state across restarts.
4. **Local MCP:** implement adapters and configure both clients during implementation. Run the acceptance flow above across REST and MCP; no separate state per client.
5. **Lifecycle cleanup and deletion:** implement Inbox aging after choosing its threshold, explicit permanent deletion, source-use checks, and reference-aware asset cleanup. Verify races with manual routing and restore.
6. **Connect UI:** wire Tasks, category/project pages, Inbox, Archive, and capture states. Replace mock autosaved/scheduled claims with actual response states.

Manual-control acceptance gate: with AI processing disabled and no MCP client connected, create/edit a project, note, and task; change a deadline/destination; add/remove an association or attachment; complete/reopen; manually resolve a capture; archive/restore; and confirm permanent deletion from Archive. Verify persistence after refresh and that subsequent stale processing cannot undo the user's changes. Add item-asset link/unlink and versioned source-correction REST operations when implementing those controls.

The first useful checkpoint is after steps 2–4: local storage plus real REST/MCP read/write workflows. Background AI, transcription, reminders/notifications, recurrence, recipe/calorie-specific behavior, and individual Skills implementations follow as separate increments. Local MCP clients provide an initial reasoning path; unprocessed captures stay visible until processed.

## Still open, without blocking the foundation

Future extension: [Personal memory and graph plan](personal-memory-plan.md) covers structured memories, evidence, automatic extraction, graph relationships and context retrieval after this backend is working. Do not implement that schema as part of the first foundation by default.

- Inbox inactivity interval; disable automatic movement until selected.
- Date-only and exact-time display details; no separate planned date will be introduced.
- Benchmark/tune Whisper small and Qwen3.5-4B locally; validate tool calling, memory use, and capture accuracy.
- Notification delivery and recurrence behavior later; no scheduler promise in the first slice.
- Detailed fields/validation for food tracking, recipes, goals, and other category-specific features.
