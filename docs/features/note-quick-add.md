# Note quick add with reviewed placement

Date: 2026-09-15
Status reviewed: 2026-09-26 — implemented through migration `20260915_0006` and commit `916d557`. The sections below preserve the design rationale; “should” language describes the implemented contract unless explicitly marked out of scope.

## Goal

Add a fast, free-text note flow that lets the user write a note and optionally describe where it belongs. Traceback saves the original input, asks the local Qwen model for a bounded title and placement suggestion, shows that suggestion for review, and creates the canonical note only after the user accepts or manually changes the destination.

This feature must remain fully usable when Qwen is stopped or returns an invalid result. The existing manual note form remains available.

## Design reference

Use the following views in `initial UI views/Modern minimal UI design/Traceback Main Page (standalone).html`:

- `15a` — Quick add note, composing
- `15b` — Quick add note, location preview
- `16a` — Choose a different folder

The mockup is visual guidance, not the product contract. Apply the current decisions when implementing it:

- Remove Today.
- Replace Everyday Life with Other.
- A selectable location may be a fixed category root, project, or folder even when the mockup informally calls everything a folder.
- Do not initiate a broader navigation or visual redesign.

## Confirmed behavior

- The user can enter an optional title, Markdown note body, and optional free-text placement hint.
- The exact submitted note and placement hint are saved before model processing.
- Qwen can propose a title and destination but cannot write directly to PostgreSQL or call arbitrary tools.
- The proposed destination is shown before the canonical note is created.
- The user can accept the suggestion, return to the note, or choose a different destination.
- The user can browse and search locations and create a folder manually.
- Acceptance creates one canonical note with one canonical ID and source provenance.
- Processing failure never loses the submitted note. Retry and manual placement remain available.
- Stale automated work cannot overwrite a later user edit or manual decision.
- The existing `/notes/new` manual path remains available without Qwen.

## Implemented design

### End-to-end flow

```text
Compose note
  -> persist original capture
  -> local processor asks Qwen for one validated proposal
  -> store the proposal without creating an item
  -> user reviews or changes the location
  -> existing interpretation transaction creates one canonical note
  -> source capture is linked to the note
```

### Composition and capture

Add a `/notes/quick-add` page and a Quick add entry in the desktop sidebar. The page should collect:

- Optional user-supplied title
- Required note body
- Optional placement hint
- Client capture time and IANA timezone

On **Find location**, call `POST /api/v1/captures` with a typed capture:

```json
{
  "source_type": "typed",
  "raw_text": "<exact note body>",
  "captured_at": "<timezone-aware timestamp>",
  "source_timezone": "<IANA timezone>",
  "timestamp_origin": "client_supplied",
  "metadata": {
    "processing_profile": "note_quick_add",
    "supplied_title": "<optional title>",
    "placement_hint": "<optional hint>"
  }
}
```

Use one idempotency key and retain the exact payload and timestamp for retries. The UI polls the capture resource while it is pending or processing.

Before the first submission, leaving the page may discard the local draft after confirmation. After persistence, leaving the flow must keep the capture available in Inbox rather than silently deleting it.

### Location catalog

The model and location picker need an unambiguous catalog of active destinations. Add a read-only REST representation that returns:

- Destination kind: category, project, or folder
- Canonical ID
- Display title
- Full breadcrumb path
- Category ID
- Current version for versioned item containers

A proposed route is:

```text
GET /api/v1/locations?q=&cursor=&limit=
```

It should derive paths from the existing single-parent `part_of` hierarchy, omit archived containers, use PostgreSQL keyword matching for `q`, and paginate deterministically. It must not create a second location identity or duplicate category/folder state.

The first implementation may instead compose this catalog from existing category/item endpoints if it can do so without incomplete results or N+1 reads. A dedicated endpoint is preferred because both the processor and UI require the same canonical paths.

### Qwen contract

Add `note_quick_add` to the allowed processing profiles. Implement a separate strict proposal schema so changes do not weaken the general-capture or task-quick-add contracts.

Qwen receives only:

- The submitted note body
- The placement hint
- The optional supplied title
- The allow-listed location catalog with canonical IDs and breadcrumbs

It may return only one proposal containing:

- A proposed title, unless the user supplied one
- One destination ID and kind, or Inbox when uncertain
- A short explanation of why the destination matches
- An optional coarse confidence label: high, medium, or low

Qwen must not rewrite the note body, invent IDs, create folders, issue writes, or propose multiple items. Unknown, archived, malformed, or type-mismatched destinations are discarded or rejected by deterministic validation.

Do not initially show a numeric value such as `92% match`. A self-reported model percentage is not calibrated. Show **Suggested location** and the explanation; add numerical confidence only after it has been measured against representative use.

### Durable proposal state

Add `awaiting_review` to the capture-processing state constraint. Add nullable proposal JSON and `proposed_at` to `capture_processing`, or an equivalent normalized representation if implementation review shows a concrete need for relational fields.

The proposal must be tied to the capture's current processing generation. Previous proposals should remain auditable through capture revisions even when the current proposal is replaced.

Add a processor-only endpoint such as:

```text
POST /api/v1/captures/{capture_id}/proposal
```

The request requires the active generation and lease token. The backend independently validates:

- The capture uses `note_quick_add`.
- Exactly one note is proposed.
- The title and explanation satisfy length bounds.
- The destination is an active allow-listed category, project, or folder.
- The destination version matches the context used for the proposal.
- The model did not supply or replace note content.
- The processor lease and generation are current.

On success, clear the lease, store the proposal, record a capture revision, and change the state to `awaiting_review`. Expose the current validated proposal through `GET /captures/{id}` so the UI can render the preview without trusting browser-held model output.

Processor lease and proposal-submission routes remain unavailable to MCP clients.

### Review and acceptance

The preview view displays:

- Supplied or proposed title
- Exact saved note body
- Full destination breadcrumb
- Placement explanation
- Back to note
- Choose a different location
- Accept and save

Acceptance should reuse `POST /captures/{id}/interpretations` in manual mode. Submit exactly one create operation using the current capture version and generation plus the current expected destination version.

Extend backend validation so a `note_quick_add` capture can resolve only to exactly one newly created note. The existing interpretation transaction then:

- Creates the canonical note once
- Uses the original or explicitly corrected note body
- Places it atomically in the chosen category/project/folder
- Creates the capture source link
- Marks the capture resolved
- Advances the generation to fence stale processor work
- Returns the canonical note ID and action ID

A stale capture, proposal generation, or container version returns HTTP 409 with no partial write. The UI keeps the user's input, re-fetches current state, and offers review rather than silently retrying with stale values.

### Choosing another location

Build a reusable location picker matching view `16a`:

- Browse category roots, projects, and nested folders.
- Search active destinations using the REST location query, not Qwen.
- Display breadcrumbs so duplicate folder names are distinguishable.
- Mark the Qwen suggestion without forcing it.
- Support keyboard focus, arrow navigation where practical, Enter to select, and Escape to cancel.
- Allow inline folder creation through the existing atomic folder/item APIs, then refresh and select the newly created canonical folder.

The final button should say **Use this location** if categories and projects are selectable; avoid presenting non-folder destinations as folders.

### Editing after a proposal

Returning to the composition view must not mutate the immutable original capture. If the user changes already-submitted content, title, or hint:

- Store the change as a versioned correction/draft revision.
- Increment the processing generation.
- Clear or supersede the old proposal.
- Requeue a fresh proposal request.

The processor must interpret the current effective corrected values while the original submitted values remain available as provenance. This may be implemented by extending the correction contract with bounded corrected note text and placement hint fields, or through a small dedicated note-quick-add revision endpoint. Choose one mechanism and document it; do not create abandoned duplicate captures for every edit.

### Failure and manual fallback

If Qwen is unavailable or returns invalid output:

- Mark processing failed with a useful message.
- Keep the original capture and all entered text.
- Offer Retry through the existing generation-controlled retry path.
- Allow **Choose location manually** and save through the same manual interpretation transaction without waiting for Qwen.

The manual path must work from pending, failed, or awaiting-review states and must fence any late processor response.

## MCP parity

Extend MCP `create_capture` with bounded `processing_profile` and `placement_hint` arguments. `get_capture` should expose the validated stored proposal through the REST response. Existing `apply_capture_interpretation` can perform the explicit manual acceptance write.

If a dedicated user-facing reprocess operation is added, expose that through MCP with the same capture-version and generation checks. Never expose lease tokens, claim/fail operations, or arbitrary model output submission to MCP clients.

## Implementation map

- Migration under `migrations/versions/`
- `backend/capture_models.py`
- `backend/capture_schemas.py`
- `backend/captures.py`
- Backend location query/service code if a shared location endpoint is added
- `processor/schemas.py`
- `processor/interpretation.py`
- `processor/runner.py`
- `traceback_mcp/tools/captures.py` and MCP registration/reference docs
- `frontend/src/app/notes/quick-add/page.tsx`
- New note quick-add and location-picker components
- `frontend/src/components/Sidebar.tsx`
- `frontend/src/lib/traceback.ts`
- `frontend/src/lib/types.ts`
- Backend, processor, MCP, and frontend tests
- `docs/backend-api.md`, `docs/processor-contract.md`, `docs/mcp-adapter.md`, `docs/mcp-tool-reference.md`, and `docs/ui-plan.md`

The frontend implementation followed the version-matched Next.js guidance referenced by `frontend/AGENTS.md`.

## Verification contract

Deterministic backend, processor, MCP, and frontend coverage was added for this feature. The checklist below records the intended coverage boundary; the repository-wide observed results are maintained in [backend-validation.md](../backend-validation.md).

### PostgreSQL-backed API tests

- The original note body, title, hint, capture time, and timezone are preserved.
- A proposal is stored without creating an item.
- Only `note_quick_add` captures can enter awaiting review.
- The backend enforces exactly one newly created note.
- Hallucinated, archived, wrong-type, and unknown destination IDs are rejected.
- Suggested category, project, and nested-folder destinations are accepted atomically.
- A manually selected destination overrides the suggestion explicitly.
- Two concurrent accept attempts produce one note and one conflict.
- Stale capture generation, capture version, and container version produce 409 without partial writes.
- Qwen failure keeps the capture available for retry and manual resolution.
- Editing and reprocessing fences the previous proposal.
- Acceptance creates one provenance link to the canonical item.
- Inbox does not show both a resolved capture and its resulting note as duplicates.

### Processor tests

- `note_quick_add` always proposes exactly one note.
- User-supplied titles are preserved.
- The body is never rewritten by the model output.
- Placement hints and full paths are supplied as context.
- Only allow-listed IDs survive validation.
- Duplicate folder names are disambiguated by breadcrumbs.
- Malformed JSON, extra fields, and attempts to inject instructions fail safely.
- A proposal is submitted instead of an item interpretation for this profile.
- Late processor responses lose to manual changes or a newer generation.

Real-Qwen tests remain optional and explicitly skipped when Ollama/model prerequisites are unavailable. Deterministic tests must not depend on Qwen being installed.

### Frontend tests

- The three mockup states render and transition correctly.
- Empty note bodies cannot be submitted.
- The exact idempotent capture payload is retained across request retries.
- Pending, processing, awaiting-review, failed, and conflict states are understandable.
- Back preserves the draft and invalidates a stale proposal after edits.
- Location search, nested browsing, manual selection, and inline folder creation work.
- Manual save remains possible with Qwen stopped.
- Accept navigates to the returned canonical note ID.
- Today never appears and Other replaces Everyday Life.
- Keyboard operation, focus movement, browser zoom, and narrower desktop windows remain usable.

### MCP tests

- Note quick-add metadata is forwarded correctly.
- The stored proposal is readable through `get_capture`.
- Manual acceptance uses the same REST validation and canonical IDs.
- Processor-only proposal and lease operations remain unregistered.

## Acceptance criteria

The feature is complete when a user can write a note and rough placement hint, receive a validated local-Qwen destination suggestion, inspect and replace that destination, and create exactly one canonical source-linked note. The same flow must recover from model failure through manual selection, preserve original and corrected inputs, reject stale writes, and pass deterministic frontend plus real-PostgreSQL API/protocol tests without using the user's live Traceback data.

## Out of scope

- Whisper or speech-to-text work
- Cloud-model fallback
- Semantic/vector search
- Automatic folder creation by Qwen
- Automatic acceptance based on confidence
- Personal-memory graph extraction
- Mobile UI
- Broad visual redesign

## Implemented contract notes

- `GET /api/v1/locations` is the shared deterministic catalog. Categories have no version; projects and folders include their current item version.
- `POST /api/v1/captures/{id}/proposal` requires the current processor lease, generation, capture version, and destination version. It is intentionally absent from MCP.
- Edits use capture corrections named `note_text`, `supplied_title`, and `placement_hint`. Originals remain immutable; a correction advances the generation, clears the old proposal, and requeues processing.
- Inbox is a null destination pair, not a second location identity. The desktop picker searches canonical breadcrumbs and can create a folder beneath a selected category, project, or folder.
