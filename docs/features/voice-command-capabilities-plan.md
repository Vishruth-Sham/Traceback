# Voice command capabilities — planning document

## Feature at a glance

Voice commands let you create a note or task by speaking a short, natural-language instruction into Traceback. You can use the microphone from the global command bar or from the supported Inbox, Tasks, note, category, project, and folder screens. The same flow also accepts a typed instruction through **Send as command**.

Traceback saves the original recording locally, transcribes it with Whisper, and uses the local Qwen model to understand the request. It then shows you a proposal containing the transcript and the note or task it understood. **Nothing is created automatically:** you must review the proposal and accept it, edit it, save it manually as a note or task, leave it in Inbox, or discard it.

### What works today

- Create one note, optionally inside an existing category, project, or folder.
- Create one task, optionally inside an existing project or folder.
- Add a date or date-and-time deadline to a task using phrases such as “next Friday at 5 PM.”
- Use natural phrasing such as “Add a note called Normal forms in Learning” or “Remind me to submit the report tomorrow.” In the latter case, Traceback creates a task with a deadline; it does not create a notification.
- Review and edit the proposed title, content, destination, and deadline before accepting it.
- Correct a transcript and ask the local processor to interpret it again.
- Recover safely when processing fails: the recording remains available in Inbox, where you can retry it, type the intended content, save it manually, or discard it.

Voice processing is local: recordings stay in Traceback's local asset storage, speech-to-text runs through local whisper.cpp, and command interpretation runs through local Ollama. There is no cloud fallback.

### What is not supported today

- Creating projects, folders, or categories by voice.
- Moving, completing, reopening, archiving, or deleting existing items by voice.
- Combining several instructions in one recording, such as “Create a project and add two notes.”
- Creating reminders or notifications. “Remind me” only creates a task with a deadline.
- Always-on listening, a wake word, keyboard shortcuts, or mobile voice commands.
- Automatic execution without review.

Keep each command short and limited to one note or one task. A named destination must already exist. If the destination is missing or ambiguous, or the request is unsupported, Traceback changes nothing and keeps the capture in Inbox for review.

The remainder of this document explains the broader design and phased plan. Some later sections describe proposed capabilities that are not part of the implemented review-first version; each technical statement retains its original **[Confirmed]** or **[Proposal]** label. For the exact implementation boundary, see [voice-commands.md](voice-commands.md).

---

Date: 2026-09-26 (revision 3, after coordinator review iteration 2)
Implementation note (2026-09-26): a review-first slice of this plan is now implemented; see [voice-commands.md](voice-commands.md) and [current status](../current-status.md) for exactly what was built, what deviates, and what remains unvalidated. The rest of this document is unchanged planning text and its status labels below describe the plan at review time.

Status of the original plan below: **PLAN ONLY at the time of review.** The feature-at-a-glance section above describes the slice implemented since that review. Every endpoint, field, state, tool, setting and threshold in the original plan is labeled **[Confirmed]** (already existed in the code/docs reviewed on that date; where a claim is an inference from reading code it says so) or **[Proposal]** (new at the time, subject to review and measurement). Nothing in this document claims that speech recognition or command understanding works well; voice/STT quality is [unbenchmarked](../current-status.md#known-limitations).

Reviewed against: [current status](../current-status.md), [initial plan](../initial-plan.md), [backend plan](../backend-plan.md), [implemented API](../backend-api.md), [UI plan](../ui-plan.md), [local models](../local-models.md), [local development](../local-development.md), [processor contract](../processor-contract.md), [note quick add](note-quick-add.md), [MCP adapter](../mcp-adapter.md), [MCP tool reference](../mcp-tool-reference.md), [folder hierarchy spec](../folder-hierarchy-backend-spec.md), and the code in `backend/captures.py`, `backend/capture_schemas.py`, `backend/capture_models.py`, `backend/assets.py`, `backend/asset_models.py`, `backend/locations.py`, `backend/config.py`, `backend/db.py`, `backend/api.py`, `backend/schemas.py`, `backend/services.py`, `processor/runner.py`, `processor/scheduler.py`, `processor/transcription.py`, `processor/interpretation.py`, `processor/schemas.py`, `traceback_mcp/tools/captures.py`, `frontend/src/app/api/v1/[...path]/route.ts`, `frontend/src/components/CaptureBar.tsx`, `TaskQuickAdd.tsx`, `NoteQuickAdd.tsx`, `frontend/src/app/tasks/new/page.tsx`.

---

## 1. Goal and non-goals

**Goal.** The user speaks (or types into the same box) one short command from anywhere in the desktop app, and Traceback:

1. **persists the original audio and a capture record before any speech-to-text (STT) runs**; only after STT can a transcript exist, and it is **checkpointed to PostgreSQL before LLM interpretation begins**;
2. works out what was asked (note, task, plain capture, organization command, or unsupported/ambiguous);
3. extracts title, content, deadline, timezone and destination as **canonical IDs** — with dates and IDs produced by **backend-owned deterministic code**, never taken from the model or the processor;
4. shows a proposal the user can accept, edit, or discard — or, later and only after a measured gate, applies it automatically for a narrow safe class that the backend can prove from stored evidence;
5. executes only bounded, validated backend operations through the existing REST transaction layer.

Example utterances that must be supported as the *first* regression corpus:

- “Add a note called Normal forms in Learning / Database Systems.”
- “Add Vendor comparison in project Kitchen renovation.”
- “Remind me to submit the report next Friday at 5 PM.” / “Add a task to submit the report next Friday at 5 PM.”

**Non-goals** (see also §19): no wake word or always-on listening, no cloud STT/LLM, no SQL or arbitrary tools for the model, no personal-memory extraction, no reminders/notifications engine, no mobile, no permanent deletion by voice, no new business rules outside REST/backend.

## 2. Requirements

### 2.1 Confirmed requirements (authoritative; from current docs)

| # | Requirement | Source |
|---|---|---|
| C1 | Sole local user; PostgreSQL, local assets, FastAPI REST, local stdio MCP; no hosted auth | [initial plan](../initial-plan.md) |
| C2 | Manual control is always available; no AI/MCP dependency for any action | initial plan, [note quick add](note-quick-add.md) |
| C3 | One canonical UUID per item across UI/REST/MCP | initial plan |
| C4 | Tasks is the only task view; optional deadline; **no planned date, no Today**; overdue tasks exist and sort first | [current status](../current-status.md), [backend-api](../backend-api.md) |
| C5 | Six fixed read-only categories; Inbox holds unresolved items; no automatic Inbox→Other | current status |
| C6 | Archive first; permanent delete is explicit, from Archive, `confirm=true` | [backend-api](../backend-api.md) |
| C7 | Originals (capture text/audio) immutable; corrections are versioned; source provenance preserved | backend-api |
| C8 | Local whisper.cpp + Ollama `qwen3.5:4b`; **no cloud fallback**; one active model job; loopback only | [processor contract](../processor-contract.md), `processor/config.py` |
| C9 | Model output is untrusted; processor makes no DB writes and holds no arbitrary tools | processor contract |
| C10 | Stale automation cannot overwrite manual edits (generation + lease + `expected_version` fencing) | backend-api, `backend/captures.py` |
| C11 | Automatic acceptance of placement proposals and automatic folder creation are deliberately deferred | current status |
| C12 | Exact-time deadlines require IANA timezone; date-only deadlines stay date-only | `backend/schemas.py`, backend-api |
| C13 | Idempotency-Key on mutations, scoped by actor/client/operation | `backend/services.py:begin_action` |
| C14 | Processor lease/claim/fail/proposal routes are not exposed through MCP | note-quick-add, mcp-adapter |

### 2.2 Verified current building blocks

Concurrency fields are listed **exactly** because this plan builds on them:

| Route [Confirmed] | Request concurrency fields today |
|---|---|
| `POST /captures` | `Idempotency-Key` (optional header) |
| `POST /captures/{id}/corrections` (`CaptureCorrectionCreate`) | `expected_version` **only** (no `expected_generation`); for the note profile the server itself bumps `generation` and requeues |
| `POST /captures/{id}/archive`, `/restore` (`CaptureVersionRequest`) | `expected_version` |
| `POST /captures/{id}/claim` | `expected_generation`, `lease_seconds` |
| `POST /captures/{id}/fail` | `expected_generation`, `lease_token`, `error_code`, `error_message`, optional `transcript` |
| `POST /captures/{id}/retry` | `expected_version`, `expected_generation` |
| `POST /captures/{id}/proposal` (note profile only) | `expected_version`, `expected_generation`, `lease_token` |
| `POST /captures/{id}/interpretations` | `expected_version`, `expected_generation`, `mode`, `lease_token` (processor mode) |

Other confirmed facts:

- **Which routes bump `Capture.version`** (each also writes one `capture_revisions` row with `resulting_version = capture.version`; `(capture_id, resulting_version)` is unique): create (=1), corrections, archive/restore, retry, fail, proposal, interpretations. **`/claim` does not bump `version` and writes no revision.** **[Confirmed]** (`backend/captures.py`, `capture_models.py`)
- Archiving a capture that is `processing` bumps `generation` and returns it to `pending` (archived, so not claimable). **[Confirmed]**
- `POST /captures/{id}/fail` **overwrites `processing.transcript` with the request’s value, including null**, so a checkpointed transcript would be lost by a `/fail` that omits it. **[Confirmed]** (see hole H21)
- `POST /api/v1/assets` streams to a temp file, fsyncs, `os.replace`s, then commits; sha256/size/MIME (`/usr/bin/file`); 413 above `max_upload_bytes` (default 100 MB). **It does not call `begin_action`, so it is not idempotent.** **[Confirmed]** (`backend/assets.py`)
- `assets.upload_state` (`ready` / `cleanup_pending`); `capture_assets` FK is `RESTRICT`; asset delete requires archive and no capture/item references; on a failed unlink it stays `cleanup_pending` and **the same explicit deletion must be re-issued — there is no background retry job**. **[Confirmed]**
- Capture delete requires the capture archived and no `item_sources` links; deleting a capture does not delete asset bytes. **[Confirmed]**
- `POST /api/v1/captures`: `source_type: "audio"` + `asset_ids`, tz-aware client-supplied `captured_at`, `source_timezone`, `timestamp_origin`, `metadata.processing_profile ∈ {general, task_quick_add, note_quick_add}`, `metadata.contextual_item_id`; `created_at` is a separate server persistence timestamp and the asset has its own `uploaded_at`. The current corrections route can edit `captured_at` and records the old/new value in revision history, so the field itself is **not** immutable. `begin_action` takes a per-key advisory transaction lock, replays a completed identical request, and conflicts on a changed payload; the endpoint commits at its end and `get_session` closes the session otherwise, so an uncommitted failure leaves no action row. **[Confirmed]**
- Processing states `pending → processing → awaiting_review | failed | resolved`; `/interpretations` takes **1–10 ops**, is whole-batch atomic, manual mode bumps generation, links provenance `interpreted`; a manual interpretation is accepted from `pending`, `failed`, or `awaiting_review` (only archived/resolved are refused). **[Confirmed]**
- `GET /inbox` returns active unclassified non-task items plus non-archived captures whose `processing.state != "resolved"` (so `pending`, `processing`, `awaiting_review`, `failed` all appear; resolved captures do not). **[Confirmed]** (`backend/api.py`)
- `GET /captures` filters by `state`, `source_type`, `archived`, `q`, ordered **`created_at DESC` (newest first)**; the runner takes `limit=1` of `state=pending` — the newest pending capture — with no aging. **[Confirmed]**
- `GET /locations` — canonical category/project/folder catalog with breadcrumb `path` and container `version`; built in `backend/locations.py`. **[Confirmed]**
- `create` interpretation op can place a new item atomically in a `project_id`/`folder_id` with the container’s expected version. **[Confirmed]**
- **No past-deadline validation** exists in `backend/schemas.py`; overdue open tasks are a first-class Tasks state. Deadlines are validated for shape, IANA zone, and DST-gap existence only. **[Confirmed by reading `TaskFields`; no rule found]**
- Runtime settings are `pydantic-settings` environment/`.env` values behind `@lru_cache` (`backend/config.py`); no writable runtime settings store or settings endpoint exists; the API is started/stopped manually per [local development](../local-development.md) (`Ctrl-C` to stop). **[Confirmed]**
- **Next.js proxy (`frontend/src/app/api/v1/[...path]/route.ts`, Next 16.3.5)**: forwards `content-type`, `Idempotency-Key`, the query string; sets `X-Traceback-Client: web` and the bearer token; **buffers the entire request body with `await req.arrayBuffer()` before calling the backend** (so the fetch to FastAPI carries a fully-buffered `ArrayBuffer` whose length the HTTP client sets); buffers the response too; `content-length` is in its hop-by-hop set (dropped from the response headers). It has no per-route body cap. **[Confirmed]**
- Processor claims one capture, downloads only the **first** audio asset, runs `whisper-cli` on an extension-less temp file, and either submits a note proposal or a general/task interpretation. **[Confirmed]**
- Global `CaptureBar` (mounted in `app/layout.tsx`) records with `MediaRecorder`, uploads with `POST /assets`, then `POST /captures` (two unlinked calls; **no idempotency key on the audio path**; no retained blob on failure) as a `general` audio capture. **[Confirmed]**
- Undo (`POST /actions/{id}/undo`) supports edit/complete/archive/move/relation actions; **creation and capture-interpretation actions are refused**. **[Confirmed]**

### 2.3 Integration holes found in the current system

| # | Hole | Evidence | Resolution |
|---|---|---|---|
| H1 | Transcript is not durable until resolve/fail; a re-run after an LLM failure re-runs Whisper. | `capture_schemas.py`, `captures.py` | Processor-only transcript checkpoint (§9.2). |
| H2 | Audio + `note_quick_add` cannot be accepted (`content_md` must equal `raw_text`, null for audio). | `interpret_capture` | Separate `voice_command` profile (§9.3). |
| H3 | Audio format is unverified: `MediaRecorder` gives WebM/Opus or MP4/AAC; whisper-cli is called on raw bytes; nothing invokes ffmpeg (installed on this Mac); `file --mime-type` may label WebM audio `video/webm`. | `CaptureBar.tsx`, `transcription.py`, `assets.py` | Phase 0 measurement; normalize to 16 kHz mono WAV with local ffmpeg (argv, timeout). |
| H4 | Only the first audio asset is transcribed. | `runner.py` | Voice profile requires exactly one asset. |
| H5 | The current mic path is an unreviewed auto-writer (`general` audio → up to 10 items, processor mode). Typed `general` and Tasks quick add also auto-apply today (separate, out of scope). | `runner.py`, `CaptureBar.tsx` | Retire the mic’s `general` path (§3, §18). |
| H6 | Deadline math is done by the model (then regex-repaired). | `local-models.md` incident | Backend-owned deterministic parser over verbatim spans (§8.3). |
| H7 | Spoken destination → ID has no home. | `runner.py` | Backend resolver over the catalog (§8.4). |
| H8 | Proposal→operation mapping would be re-implemented by each client. | note quick add | Backend `accept` (§9.3). |
| H9 | Creation via interpretation is not undoable via `/actions/{id}/undo`. | `services.py` | Voice “Undo” = archive the created item. |
| H10 | No policy layer decides auto-apply vs review, and — as drafted in revision 2 — the policy would have consumed **processor-asserted** facts. | `runner.py` | Backend-owned pure policy recomputed from stored evidence (§7.4). |
| H11 | MCP cannot upload audio. | `traceback_mcp/tools/assets.py` | Deliberate exclusion; typed voice via MCP (§11). |
| H12 | Queue is newest-first with no aging, polled every 15 s, single job. | `captures.py`, `scheduler.py` | Backend `claim-next` (§13.4). |
| H13 | No “processor unavailable” signal. | UI polls capture state only | Age-based “waiting” + queue stats in capabilities. |
| H14 | No local quality telemetry. | — | Derived from PostgreSQL revisions + content-free log (§14). |
| H15 | `POST /assets` + `POST /captures` is not atomic/idempotent; `CaptureBar` keeps no blob to retry. | `assets.py`, `CaptureBar.tsx` | One-request idempotent voice ingest + reconciliation (§9.1a). |
| H16 | `config.py` is env-loaded/cached; `NEXT_PUBLIC_*` is build-time and client-visible. | `config.py` | Single backend env source + `/capabilities` (§9.5). |
| H17 | `capture_only` cannot “resolve and stay in Inbox”. | `capture_schemas.py`, `api.py` | Stays `awaiting_review` (§3, §5). |
| H18 | Archiving a capture does not reclaim audio; deleting requires archive-first, no provenance links, then asset archive+delete. | `asset_models.py`, `assets.py`, `captures.py` | Storage lifecycle obeying archive-first (§14.3). |
| H19 | Manual accept/override is only visible in the resulting item’s revision. | `interpret_capture` | Server-diffed override audit in capture revisions (§9.3). |
| H20 | The proxy buffers the whole body; a backend preflight cannot prevent that. | `route.ts` | Bounded proxy change (§9.1a). |
| H21 | `/fail` overwrites `processing.transcript` (even with null), which would destroy a checkpoint. | `captures.py:fail_capture` | For `voice_command`, `/fail` preserves an existing transcript when the request has none (§9.2). |
| H22 | Client `captured_at` and server receipt `created_at` can diverge (offline retry, wrong clock); the anchor for relative dates must not be silently swapped. | `CaptureCreate`, `Capture.created_at` | §8.3. |

## 3. Product decisions (resolved)

| Decision | Resolution | Rationale |
|---|---|---|
| Command vocabulary vs natural language | **Natural language is the product; no required vocabulary or modes.** The three example phrasings are the *seed regression corpus*, not a grammar. No deterministic verb fast-path in v1; reconsider in Phase 5 only if measured latency/error justifies it. | Two code paths double the surface to fence. |
| Capture-first | Audio bytes + capture record persisted (one atomic, idempotent request, §9.1a) **before** STT. The transcript exists only after STT and is checkpointed **before** the LLM stage. Failures leave audio (+ transcript if it exists) in Inbox. | C7, C10. |
| Who owns what | The **model (processor) proposes spoken-form slots only**. The **backend owns all deterministic logic** — grounding, intent policy, date parsing, destination resolution, disposition — in one pure package, recomputed from stored evidence (§7.4). Processor-reported verdicts (groundedness, lexicon agreement, warnings, flags, IDs, eligibility) are not accepted at all. | Trust boundary; no duplicated rules. |
| Model confidence | Stored **locally for offline evaluation only**; **never displayed as product truth** (no High/Medium/Low badge, no percentage) and **never an input to disposition or auto-apply**. The card explains proposals with deterministic warnings/reasons instead. | Uncalibrated. |
| Default execution mode | **Review-first for everything** at launch. Auto-apply is a backend policy that ships **off** (env, §9.5), enabled per intent only after the §15 gate, and only for a class the backend can prove (§7.4). | C11. |
| Intents in scope | `create_note`, `create_task`, `capture_only`, plus (Phase 4, review-only) `move_item`, `complete_task`, `reopen_task`, `archive_item`. Others → `unsupported`; unclear → `ambiguous`. | Bounded. |
| **`capture_only` / `unsupported` / `ambiguous` lifecycle** | Not resolutions. The capture goes to **`awaiting_review`** (listed by `GET /inbox`) and **stays there until the user acts**. A capture is a source record and **has no folder/location**; only the *item created from it* is placed. Card actions: **Save as note** (with an optional destination picker inside the action), **Save as task** (with optional project/folder container and deadline inside the action), **Keep in Inbox** (no-op), **Discard** (archive). No “Choose location” action exists on a raw capture and no raw-capture location endpoint is implied. It becomes `resolved` only when a create/append runs. | H17. |
| Generic “Add X in Y” intent | §8.5. Explicit words win → temporal/imperative inference → force-review default. Surface context is a restriction/hint, never silent authority. | — |
| Multi-intent | v1: detect and do not execute (`ambiguous`, `awaiting_review`); Phase 4 offers a user-confirmed split (≤ 3 create-only, atomic). | No silent partial execution. |
| Corrections / cancel | Pre-upload cancel discards the in-memory recording (nothing persisted). Post-upload discard = archive. No spoken “cancel”. `self_correction` → forced review. Transcript edits use the correction route (§9.4) or the manual escape hatch (§10.1). | Spoken cancel is an untrusted command channel. |
| Missing destination | Inbox (null destination pair); stated-but-unresolvable → Inbox + review, `not_found`; voice never creates folders (C11). | — |
| Duplicate folder/project names | Never guess; ≥ 2 candidates → `ambiguous`, none preselected. | §8.4. |
| Timestamps | The client-observed capture time is preserved at ingest and is the initial date **anchor**; `created_at` (server persistence) and asset `uploaded_at` are distinct. An audited manual correction may change the effective `captured_at` anchor while preserving the original value in capture metadata/revisions; divergence forces review and is shown; the anchor is never silently replaced (§8.3). | H22. |
| Dates and past deadlines | Deterministic parser; weekday/time-of-day rules in §8.3. **No global ban on past deadlines** (overdue tasks are supported): manual review may explicitly confirm an overdue deadline; **auto-apply rejects any past deadline.** | C4. |
| “Remind me” | Maps to `create_task` with a deadline. No reminders/notifications exist; copy says “Task added with deadline”. | Avoids a false promise. |
| Duplicate submissions | Capture idempotency key + server sha256 duplicate guard + near-duplicate title warning; distinct from asset idempotency (§9.1a, §10). | C13. |
| Accidental mic activation | Click-to-toggle only in v1; **no keyboard shortcut/global hotkey**; visible indicator; auto-stop at 60 s; < 0.7 s or `no_speech` never sent to Qwen and kept as `failed` (`no_speech`) with Discard; no wake word. | Privacy + originals. |
| Disabled / rolled-back behavior | Command mic **disabled with a reason**; typed capture unaffected; **never a fallback to the legacy `general` audio path** (retired from the UI in Phase 3; the backend `general` audio path frozen to review in Phase 1). **A manual escape hatch works while disabled** (§10.1). | H5. |
| Background/offline models | Capture persists whenever REST, PostgreSQL and disk are available (exceptions in §10). Processor down → `pending`; “Waiting for local processor” after 20 s; manual escape hatch available. | C2, C8. |
| Undo | Create → “Undo” = archive the new item; capture retained. Phase 4 mutations use generic undo. | H9. |
| Priority / latency | Bounded, backend-owned, aged priority via `claim-next` (§13.4). | H12. |
| Audio reclaim | **v1 only via the existing archive-first chain** (§14.3). No irreversible audio-discard shortcut is in v1 scope. | C6, C7. |

## 4. Product / runtime flow

```text
User clicks a launcher (global mic, or a context button that opens the SAME global recorder)
  │  ① single-recording mutex (per tab: provider state; across tabs: Web Locks) — nothing is sent until Stop
  ▼
Browser ── GET /capabilities  (fresh, no-store; enabled? limits? low_disk?) ─────────────► [Proposal]
Browser ── POST /voice-captures?size=…&sha256=…&captured_at=…&source_timezone=…
           &entry_point=…&contextual_item_id=…&allowed_intent=… (raw audio body) + Idempotency-Key
           via the Next proxy (bounded buffering, §9.1a) ── ONE backend transaction:
           bytes + asset + capture + revision ─────────────────────────────────────────► [Proposal]
              (replay of the same key returns the recorded capture; no second asset)
  │  ② card "Saved • transcribing"; polls GET /captures/{id}                             [Confirmed]
  ▼
Processor (single loopback process, one job at a time)
  POST /captures/claim-next (backend picks: aging + bounded voice preference) ──────────► [Proposal]
  download asset ─► ffmpeg normalize (local) ─► whisper.cpp small
  POST /captures/{id}/transcript (lease+generation; NO version bump) ───────────────────► [Proposal]
  Qwen (Ollama, loopback): transcript → strict JSON SLOTS (no IDs, no computed dates)
  POST /captures/{id}/proposal { slots, model_confidence, stt meta } ─────────────────► [Proposal]
        └─ BACKEND recomputes from stored evidence (transcript, captured_at/created_at/tz, metadata,
           live catalog, now, policy): grounding, intent policy, dates, destination IDs/versions,
           warnings, disposition ∈ {review, reject, auto_apply_eligible}; stores CommandProposal
  │  state → awaiting_review   (or failed with a specific error_code)
  ▼
Review card (transcript, audio, intent, title, content, deadline+tz, destination breadcrumb, deterministic warnings)
  Accept ── POST /captures/{id}/proposal/accept ────────────────────────────────────────► [Proposal] → existing interpretation transaction
                                                              (+ overdue confirmation, + server-diffed override audit)
  Save as note / task ── existing manual POST /captures/{id}/interpretations             [Confirmed route; voice rule §9.3]
  Edit transcript ── corrections route (transcript_text) → requeue (only while enabled)  [Proposal field]
  Discard── POST /captures/{id}/archive                                                  [Confirmed]
  Undo   ── POST /items/{id}/archive (expected_version)                                  [Confirmed]
```

Authority boundaries: the browser applies nothing from model output; the processor has no DB access and supplies **only evidence-bearing inputs** (audio-derived transcript, model slots); **only the backend computes proposals and only the backend transaction creates items**; Qwen emits text only.

## 5. State machine and version mechanics

Existing states [Confirmed]: `pending`, `processing`, `awaiting_review`, `failed`, `resolved`, keyed by `generation`. **[Proposal]: no new states**; `ck_capture_processing_state` is untouched. `capture_only`, `unsupported` and `ambiguous` outcomes are `awaiting_review` proposals.

```text
   create (audio+asset, one request)        claim / claim-next (gen g)       transcript checkpoint (no version bump)
  (none) ─────────────────────────► pending ───────────────────► processing ───────────────────────────► processing
                                       ▲  ▲                          │                                      │
                         retry(g+1)    │  │ correction(g+1)          │ fail(error_code)                     │ proposal(g)
                       (failed only)   │  │  (only while enabled)    ▼                                      ▼
                                       └──┴───────────── failed ◄─────┴────────────────────────── awaiting_review
                                                             │                                          │ (also capture_only / unsupported / ambiguous:
                                                             │ manual interpretation (g+1)              │  stay here until the user acts)
                                                             └────────────► resolved ◄─────────────────┘ accept / save-as / manual interpretation (g+1)
      archive (any unresolved state) ─► archived capture (original retained; processing → generation+1; late processor work rejected 409)
```

### 5.1 Version, generation and lease — how they interact [Proposal, on top of Confirmed bump rules in §2.2]

- **Transcript checkpoint does not increment `Capture.version` and writes no `capture_revisions` row.** Reason: `(capture_id, resulting_version)` is unique, so a revision would force a bump, and a bump would make a user-held `expected_version` stale for no user-visible reason (false conflicts), and would invalidate the version the runner read after `/claim` and reuses for `/proposal`. The checkpoint is fenced by **lease + generation** only. Its evidence is recorded in the **next** revision written by the same generation (the `proposal` or `processing_failed` revision): `transcript_sha256`, `transcript_length`, `stt_model_id`, `language`, `duration_ms`, `transcript_checkpointed_at`. The transcript text itself lives in `capture_processing.transcript`, which changes only under a live lease at the current generation (or by manual interpretation).
- **`/proposal`, `/fail`, retry, correction, archive, interpretations** bump `version` as today (each writes exactly one revision with a unique `resulting_version`). **`/claim`, `/claim-next` and `/transcript` do not bump.** So `version` moves only at **user-visible transitions**.
- Every **user** action that changes the capture either bumps `generation` (correction, manual interpretation, accept, archive-while-processing) or makes it unclaimable (archive of a non-processing capture). Therefore a processor call that survives has an unchanged `version` and `generation`; any other processor call gets a **409** and is discarded (safe, never a false success).
- **How polling clients refresh:** the card polls `GET /captures/{id}` (≈ 1.5 s, existing pattern) and always sends the `version` and `generation` from the latest response with any action. A `409` response’s `details` carries the current `version`, `generation`, `state` and `proposal_sha256`; the client refetches. If `generation` and `proposal_sha256` are unchanged and the card holds no unsaved edits it silently resubmits once; otherwise it re-renders the fresh proposal **keeping the user’s edits** and asks again.
- **Lease** is only for processor calls; lease expiry with no other change lets a later claim proceed at the same generation.

Rules:

- Every mutation carries the concurrency fields in §2.2 (or proposed additions in §9); stale → HTTP 409, no partial write.
- **`resolved` is reached only by creating/appending ≥ 1 item.** From `awaiting_review`, re-queue happens only by correction (generation++); from `failed`, by retry (generation++).
- `disposition` values are exactly `review`, `reject`, `auto_apply_eligible`. `reject` means “no write is proposed”; the capture stays `awaiting_review` with a reason, unless backend validation of the *submission* failed, in which case the processor marks it `failed`.
- Proposals never silently change meaning: dates are grounded on `captured_at`; Accept re-validates versions, catalog and deadline at commit time.

## 6. Entry points — one shared launcher and review component

**Architecture [Proposal].** All entry points share one client module: one recorder state machine, one upload/retry implementation, one review UI:

- `VoiceCommandProvider` mounted once in `app/layout.tsx` next to `CaptureBar`. Owns: capability state (`GET /capabilities`), the recorder state machine (`idle → requesting_permission → recording → stopping → uploading → saved | failed_unsent`), the retained blob + Idempotency-Key + `captured_at`/timezone/sha256 for retries, and the tray of in-flight/awaiting-review voice captures.
- `VoiceLaunchButton` — presentational; context launchers only call the provider with `{entry_point, contextual_item_id?, allowed_intents?}` and contain no recording, upload or polling logic.
- `CommandReviewCard` — the single review/accept/edit/discard UI, rendered in the global tray, the Inbox row, and a `/captures/{id}` deep link.
- **Single-recording mutex.** A second recording is refused while state ∈ {`requesting_permission`, `recording`, `stopping`, `uploading`, `failed_unsent`}: it focuses the active recorder and toasts “Already recording (started from <entry point>)”. `failed_unsent` blocks new recordings until Retry, **Save recording to a local file** (download of the retained blob), or Discard. Across tabs: `navigator.locks.request("traceback-voice-recorder", {ifAvailable: true})`; unavailable → “Recording is active in another window”. Double-clicks are collapsed by the state machine and the idempotency key.
- The provider lives in the root layout so client route changes do not destroy it; a `beforeunload` guard warns during `recording`, `uploading`, `failed_unsent`.

| Surface | Today | Change [Proposal] |
|---|---|---|
| Global `CaptureBar` mic | `general` audio capture, auto-interpretation | Becomes the provider’s global launcher. With voice off it is **disabled with a tooltip** (never the legacy path). Typed text stays a `general` typed capture; **no implicit command parsing of typed text**; an explicit “Send as command” toggle posts typed text as `voice_command` via `POST /captures` (no audio, no STT). |
| Tasks page (`TaskQuickAdd`) | typed `task_quick_add`, inline card | Typed flow unchanged. Adds a `VoiceLaunchButton` (`allowed_intents:["create_task"]`, `entry_point:"tasks"`). Result is the shared review card — **not form-filling** (transcription is asynchronous in the local processor; **no browser STT**). “Open full form” reuses `/tasks/new?raw=&captureId=&captureVersion=&captureGeneration=` **[Confirmed pattern]** so no duplicate item or second state machine. |
| Notes: `/notes/quick-add`, `/notes/new`, note detail | typed reviewed placement / manual forms | Unchanged. “Dictate a note” launcher (`allowed_intents:["create_note"]`, `entry_point:"notes"`) opens the same recorder; result is the shared card. Phase 3 checks whether `/notes/new` can take a capture-resolving prefill; if not, inline editing on the card is the only edit path (no new prefill route invented). |
| Inbox | lists non-resolved captures | Voice captures show transcript preview, stage badge, audio player, “Needs review”, Review/Discard. `awaiting_review`, `failed`, `pending`, `processing` are already listed **[Confirmed]**. |
| Project / folder / category pages | contextual forms | Launcher with `contextual_item_id` = that container (a **hint**, §8.5). |
| Item detail panel | edit/move/relations | Unchanged (manual). Phase 4 organization commands end in the review card. |
| Search | keyword | Unchanged; used server-side for duplicate warnings. |
| Archive | archive lists | Voice captures listed; storage/cleanup section (§14.3). |
| Skills | static register | “Voice commands”: **Planned** until the gate passes, then **Available (review-first)**, driven by `capabilities`. |
| Manual forms everywhere | — | Always available (C2). |

Keyboard: card supports Enter = Accept, E = Edit, Esc = close (not discard); discard needs an explicit action + confirm. **No recording shortcut in v1.**

## 7. Interpretation contract and trust boundary

### 7.1 Model output (Qwen) — spoken-form slots only [Proposal]

The processor validates Qwen’s output against a strict schema (`extra="forbid"`; separate from the general/task/note schemas) and submits **only these slots**. **The model gets no database schema, no SQL, and no tools; it necessarily receives the strict JSON output contract in its prompt.**

```json
{
  "intent": "create_note | create_task | capture_only | move_item | complete_task | reopen_task | archive_item | unsupported | ambiguous",
  "title": "string ≤ 500 | null",
  "content": "string | null",
  "destination_phrase": "verbatim span | null",
  "target_phrase": "verbatim span | null",
  "date_phrase": "verbatim span | null",
  "time_phrase": "verbatim span | null",
  "flags": ["multi_intent", "self_correction", "unclear_audio", "requested_delete", "unsupported_request"],
  "confidence": "high | medium | low",
  "reason": "≤ 300 chars"
}
```

The model never emits IDs, ISO dates, weekdays, offsets, timezones, or verdicts. Prompt inputs: transcript, allowed intents, timezone *name* (context only). The catalog is not sent (resolution is deterministic and backend-side).

### 7.2 Submission body [Proposal]

`POST /captures/{id}/proposal` (union with the existing note body) for `voice_command` accepts exactly: `expected_version`, `expected_generation`, `lease_token`, `slots` (above minus `confidence`), `model_confidence` (evaluation only), `stt` (`stt_model_id`, `language`, `duration_ms`). `extra="forbid"`: **any other processor-supplied field — grounding results, warnings, resolved IDs/versions, candidates, dates, dispositions, eligibility — is rejected (422), not ignored.**

### 7.3 Stored proposal (`CommandProposal`) — computed by the backend [Proposal]

Stored in `capture_processing.proposal` (JSONB) with `generation`, `inputs_sha256` (hash of the submitted slots + the evidence versions used), `policy_version`, and `policy_evaluated_at`. Note proposals are unchanged.

```json
{
  "kind": "voice_command", "schema_version": 1, "generation": 3,
  "inputs_sha256": "…", "policy_version": 1, "policy_evaluated_at": "2026-09-26T10:14:31+05:30",
  "intent": "create_task",
  "operation": {
    "type": "create", "item_type": "task",
    "title": "Submit the report", "content_md": "",
    "due_date": "2026-10-02", "due_time": "17:00:00", "due_timezone": "Asia/Kolkata",
    "destination": null
  },
  "resolution": {
    "intent": {"basis": "explicit_reminder_verb", "lexicon_agrees": true},
    "anchor": {"captured_at": "2026-09-26T10:14:00+05:30", "received_at": "2026-09-26T10:14:02+05:30", "skew_s": 2},
    "date": {"phrase": "next Friday", "time_phrase": "5 PM", "basis": "next_calendar_week_weekday",
             "default": "2026-10-02", "alternatives": ["2026-10-09"]},
    "destination": {"status": "none", "phrase": null, "source": null, "candidates": []}
  },
  "warnings": ["date_ambiguous_next_weekday"],
  "model_confidence": "medium",
  "explanation": "Recognized a task with a Friday 5 PM deadline.",
  "disposition": "review",
  "disposition_reasons": ["next_weekday_requires_review", "auto_apply_disabled"]
}
```

`model_confidence` is stored for offline evaluation and **not rendered**. For `capture_only` / `ambiguous` / `unsupported`, `operation` is `null`; `disposition` is `review` (capture_only, ambiguous) or `reject` (unsupported); the capture remains `awaiting_review`.

### 7.4 Ownership model and trust boundary (one implementation)

**Decision: backend recomputation using a single backend-owned pure package** (`backend/voice_policy/`, no I/O, no DB or network imports; the catalog, transcript, timestamps and `now` are passed in as arguments). It contains: normalization + grounding check, intent lexicon policy, date/time parser and weekday rules (§8.3), destination resolver (§8.4), warning derivation, and the disposition engine (§12). The **processor contains none of these rules and imports nothing from it**; the same package is imported by tests and by the offline evaluation script, so the corpus tests exercise exactly what production runs (no duplicate implementation to drift). The backend builds the catalog by reusing the catalog builder from `backend/locations.py` in-process (no HTTP round-trip, no processor-supplied catalog).

**Untrusted processor outputs (suggestions):** the whole slot set (intent, title, content, phrases), `flags`, `model_confidence`, `stt` metadata, and the **transcript itself** (see residual below). Model `flags` may only *add* review-forcing flags; the backend takes the union with its own derived flags and can never be lowered by the processor.

**Backend-derived facts (never accepted from the processor):** groundedness of each span (checked against the stored transcript), lexicon agreement / intent basis, all dates, all warnings, resolved destination/target IDs, versions and candidates, `allowed_intents` enforcement (from stored capture metadata), overdue/skew/DST checks, `disposition`.

**Auto-apply is backend-provable (Phase 6).** In processor-mode `/proposal/accept` the backend **recomputes the entire proposal from stored evidence at that moment** — stored transcript (typed captures: the immutable `raw_text`), stored slots, the capture’s `captured_at`/`created_at`/timezone/metadata, the **current** catalog, the **current** time, and the **current** policy — and requires: recomputed `disposition == auto_apply_eligible` **and** recomputed operation == stored operation (else 409 `proposal_stale`, and the capture stays `awaiting_review` for manual review). Nothing the processor asserted is consulted.

**Residual trust, stated plainly.** For audio captures the backend cannot re-run STT; the processor-provided transcript is the trust anchor. This is the same-host, same-user local processor (C1, C8), and the auto-apply class is deliberately narrow (explicit reminder/task word, no destination, warning-free future deadline) and undoable by archive. The Phase 6 gate therefore also requires an **offline audit** that re-transcribes the retained audio of auto-applied captures and compares (script, no cloud). Typed voice commands (MCP or “Send as command”) have no such residual.

## 8. Extraction rules (all implemented in the backend package, §7.4)

### 8.1 Title / content

- “Add a note called X …” → title X, content empty. “Note: X …” / “Remember that …” without a title → title = first ≤ 8 words of the span, content = the span (`title_derived` → review).
- Task title excludes date/time spans and leading verbs (“remind me to”, “add a task to”).
- Body is never rewritten or summarized; only transcript spans are copied. The transcript stays on the capture.

### 8.2 Timezone

`due_timezone` = the capture’s `source_timezone` (browser IANA zone), never a model value. Date-only deadlines carry no timezone [Confirmed rule].

### 8.3 Dates, times and timestamps — deterministic authority

**Distinct timestamps are preserved and shown.** `captured_at` is the effective user/client capture time [Confirmed field, `timestamp_origin="client_supplied"`]; `created_at` is the server persistence time [Confirmed field], and the audio asset has `uploaded_at` [Confirmed field]. **[Proposal]** Voice ingest also copies the initially observed client time into immutable source metadata and the `created` revision. A later explicit manual timestamp correction may change effective `captured_at`, but must record old/new values, bump generation, clear the proposal, and re-run interpretation; it never erases the initially observed value. The proposal stores the effective anchor, original observed time, `created_at`, `uploaded_at`, and their deltas (`resolution.anchor`).

**Anchor rule.** Relative language is resolved against **`captured_at` in `source_timezone`** — the moment the user actually spoke — even if ingestion or processing was delayed (an offline retry hours later must still interpret “tomorrow” as the day after the utterance). **The anchor is never silently replaced with receipt time.**

**Skew / delay review flow.**

| Condition | Flag | Behavior |
|---|---|---|
| `skew_s > 300` (received > 5 min after captured: offline retry, slow upload, wrong clock behind) | `delayed_ingest` | Anchor stays `captured_at`. Card shows both times (“Spoken Fri 26 Sep 10:14 · saved 13:40”). **Every relative phrase** (today/tomorrow/weekday/offset/time-only) forces review. If interpreting under the receipt anchor would give a different date, it is listed as an alternative chip. Never auto-applied. |
| `skew_s < −120` (captured_at in the future vs receipt: device clock ahead) | `clock_ahead` | Same: primary = `captured_at`, alternative under the receipt anchor, review, never auto-applied. |
| within bounds | — | No flag. |

Absolute dates (“October 5, 2027”) are unaffected by skew. Queue wait between receipt and processing does not change the anchor.

**Weekday and time-of-day semantics.** Let the anchor’s local date be *D*, weekday *W*, local time *T*. Examples use **Saturday 2026‑09‑26 10:14** unless stated. Weeks are Monday–Sunday.

| Spoken | Resolution | Effect |
|---|---|---|
| “today”, “tomorrow” | *D*, *D*+1 | eligible (no time) |
| Bare or “this” weekday ≠ *W* (“Friday” on a Saturday) | next occurrence strictly after *D* (2026‑10‑02) | eligible |
| **Bare weekday = *W*** (“Friday” said on Friday 2026‑10‑02) | **ambiguous**: today vs +7. Default = **today** when a time is given and it is still ahead of *T*; otherwise default = **+7**; the other is the alternative | **review** (`date_ambiguous_same_weekday`) |
| “**this** Friday” said on Friday | today; if a time is given and already ≤ *T* → default +7 with `time_passed_today` | eligible / review |
| “**next** Friday” | the Friday of the **next Monday-start calendar week**; alternatives: nearest upcoming Friday if different, else +7 (Sat 2026‑09‑26 → default 2026‑10‑02, alternative 2026‑10‑09; Wed 2026‑09‑23 → default 2026‑10‑02, alternative 2026‑09‑25) | **review** (`date_ambiguous_next_weekday`) |
| “in 3 days”, “in two weeks” | offset from *D* | eligible |
| “today at 9 AM” said at 10:14 (time already passed) | date = *D*, time as spoken | **review** (`time_passed_today`); becomes an overdue deadline if confirmed |
| “at 5 PM” with no date | next future occurrence after *T* (today if ahead, else tomorrow with `date_assumed`) | review if rolled to tomorrow |
| “tonight”, “this evening”, “this morning” | date *D*; no clock time assumed unless spoken (`time_assumed` if the model gave a period word) | review |
| “tomorrow at 5”, “at 5” (no meridiem) | `meridiem_assumed` (heuristic shown) | review |
| “midnight Friday” | ambiguous (start vs end of Friday) → both shown | review |
| “October 5th”, “5 October”, “5th of Oct” (month names/abbrevs, ordinals, spoken numbers) | month+day; **year absent → nearest occurrence on or after *D*** (never a past date); > 90 days out → `year_assumed` | review when > 90 d |
| “October 5, 2027” | explicit year accepted; two-digit years → review | eligible / review |
| Numeric “5/10”, “5-10-27” | locale-ambiguous; parse only if exactly one reading is valid, otherwise show both readings, none preselected | **review always** |
| “yesterday”, “last Friday”, explicit past date | resolved as spoken, `deadline_past` | **review** (§ below) |
| “end of month”, “next week”, “soon” | not resolvable → `due_*` null, phrase kept in `content_md` (existing contract rule) | review (`date_unresolved`) |

**Past and overdue deadlines — no global ban.** Overdue tasks are a supported Traceback concept (C4); the REST validation has no past-date rule [Confirmed], so a manually created overdue task is legitimate (e.g. “add a task: I owed the report last Friday”). Voice therefore adds only these rules:

- **Review/manual:** a past deadline (at parse time, or **at accept time** — e.g. “5 PM today” accepted at 6 PM) is allowed **only with explicit confirmation**. `POST /captures/{id}/proposal/accept` evaluates the deadline against the server’s current time in `due_timezone` (date-only: `due_date < today` there) and, if overdue, returns **422 `overdue_confirmation_required`** with `overdue_by`, unless the request carries `confirm_overdue: true`. The card shows “This deadline has passed by 1 h. Add as overdue?” The confirmation is recorded in the audit (§9.3). Manual `/interpretations`, `POST /items` and the manual forms keep today’s behavior (no new rule).
- **Auto-apply:** any deadline earlier than *now at accept time* is **not eligible** (recomputed by the backend, §7.4); a deadline of *today* is eligible only if it is date-only or its time is still ahead.

**DST / timezone.** Stored value is local wall time + IANA zone [Confirmed], so a repeated hour needs no special storage; a **nonexistent** time (spring-forward gap) fails the existing `TaskFields` check → the proposal carries `dst_gap` with the nearest valid alternatives (+1 h) and requires review; never adjusted silently. Test zones: America/New_York, Europe/London, Asia/Kolkata, Australia/Lord_Howe.

**Locale.** Spoken-date parsing is English (`whisper_language="auto"` may emit other languages; a non-English transcript → `unsupported_language` → review). Numeric formats follow the ambiguity rule regardless of machine locale. **No planned date** is ever produced (C4).

### 8.4 Destination resolution (backend, over the live catalog)

Order (casefold, punctuation-insensitive; spoken “slash”/“then” normalized to `/`): (1) exact full `path` → `resolved/high`; (2) `Category / …` prefix + unique leaf → `resolved/high`; (3) unique leaf across the catalog → `resolved/medium`; (4) unique fuzzy (edit distance ≤ 1 on tokens ≥ 5 chars) → `resolved/low` (**review always**); (5) ≥ 2 best-tier candidates → `ambiguous` (none preselected); (6) none → `not_found` → Inbox + review. “in project Y” restricts to projects, “in folder Z” to folders; category aliases map to the six fixed categories. Archived containers are absent from the catalog [Confirmed], so they cannot resolve. IDs and versions come only from this step.

### 8.5 Intent policy for generic utterances

Deterministic, in order; the model’s intent must agree or `intent_conflict` (review).

1. **Explicit type word wins.** “add a **note** called …”, “note: …” → note; “add a **task** …”, “**remind me** to …”, “to-do: …” → task. Both a note noun and a reminder verb (“add a note to remind me to call mom tomorrow”): the noun that is the object of “add/create/make” wins; alternative shown; `intent_conflict` → review.
2. **Inference without a type word** (always `intent_inferred` → review, never auto-applied): an actionable deadline + a leading base-form action verb from a bounded lexicon (call, email, submit, send, buy, pay, book, finish, schedule, renew, …) → task; “Add/Put/Save X in/to Y” with a noun-phrase X (no lexicon verb, no deadline) → note titled X; “Add <lexicon verb> …” → task in that container.
3. **Anything else** → `ambiguous`; selector **Note | Task | Just keep it**, nothing preselected.
4. **Surface context is a restriction or hint, never authority.** `allowed_intents` is stored on the capture and **enforced by the backend recompute**: an out-of-scope intent becomes `unsupported` (“This launcher only creates tasks — use the global mic”), nothing is written, the capture stays `awaiting_review`. `contextual_item_id` only fills a missing destination as `source:"surface_context"`, shown as “Suggested: this project”, always review, never auto-applied, never overriding a spoken destination.

| Utterance | Basis | Proposal (abbreviated) |
|---|---|---|
| “Add a note called Normal forms in Learning / Database Systems” | rule 1 | note “Normal forms”, folder `Learning / Database Systems` (`resolved/high`) |
| “Add Vendor comparison in project Kitchen renovation” | rule 2 (noun phrase) | note “Vendor comparison”, project; `intent_inferred` → Note/Task toggle |
| “Add call the plumber in project Kitchen renovation” | rule 2 (verb) | task “Call the plumber”, project; `intent_inferred` |
| “Submit the report by Friday” (Saturday capture) | rule 2 | task, due 2026‑10‑02, `intent_inferred` |
| “Remind me to submit the report next Friday at 5 PM” | rule 1 | task, default 2026‑10‑02 17:00 Asia/Kolkata, alternative 2026‑10‑09, `date_ambiguous_next_weekday` |
| “Remind me to file it Friday at 5 PM” said Fri 10:14 | rule 1 | task; `date_ambiguous_same_weekday`, default today 17:00, alternative +7 |
| “Add a note to remind me to call mom tomorrow” | rule 1 conflict | note, alternative task; `intent_conflict` |
| “Dad’s birthday gift ideas” | rule 3 | `ambiguous`; no default; stays `awaiting_review` |
| Tasks page: “Add a note called X” | rule 4 | `unsupported` (restricted launcher); no write |
| Project page: “Add a task to book the venue” | rule 1 + hint | task; destination `surface_context` suggested, review |
| “Delete my old notes” | — | `unsupported` (`requested_delete`); no write |

## 9. REST / schema proposals (all [Proposal]; confirmed fields per §2.2)

Design rule: **no business rule lives outside the backend/REST.** The processor supplies evidence-bearing inputs; the backend computes and decides.

### 9.1 Capture profile

Extend `CaptureMetadata.processing_profile` with `"voice_command"`; add bounded `allowed_intents`, `entry_point ∈ {global, tasks, notes, project, folder, category, inbox, mcp_typed}`, `duration_ms`. For `voice_command`: `captured_at` + `source_timezone` **required**; typed or audio (audio has **exactly one** asset); 403 `capability_disabled` when voice is disabled (§9.5). Migration: none (JSONB).

### 9.1a Atomic idempotent voice ingest — `POST /api/v1/voice-captures`

Problem (H15): `POST /assets` + `POST /captures` is not atomic and `POST /assets` is not idempotent. **Capture idempotency and asset idempotency are different problems; the voice path becomes one request with one key.**

**Protocol.** Raw audio body; **required** `Idempotency-Key` header (400 if absent); **query parameters** (the proxy forwards the query string): `size` (bytes, **authoritative**), `sha256` (hex, client-computed with `crypto.subtle`), `filename`, `captured_at`, `source_timezone`, `entry_point`, `contextual_item_id?`, `allowed_intent*`, `duration_ms?`. **`Content-Length` is not required by the protocol** (the proxy may re-send the body chunked or with a computed length); when present it must equal `size`. The authoritative checks are: counted bytes == `size`, streamed sha256 == `sha256`, and counted bytes ≤ `voice_max_upload_bytes`.

**Backend order of operations.**
1. Validate capability, parameters, declared `size` ≤ cap and free disk (`voice_min_free_disk_bytes`) **before reading the body** → 403 / 413 / 507. *(This avoids writing to disk; it does not avoid any buffering that happened earlier in the proxy — see below.)*
2. `begin_action("create_voice_capture", payload = {size, sha256, meta}, key)` — per-key advisory lock [Confirmed mechanism]. A completed identical key returns the recorded capture **without reading the body or touching disk**; a different payload → 409 `idempotency_conflict`; a concurrent duplicate blocks then replays.
3. Stream to a temp file with a running digest and size cap; fsync; verify digest and size (mismatch → 422 `digest_mismatch` / `size_mismatch`); detect MIME against the accepted list (Phase 0-measured; 415 `unsupported_media`); `os.replace`; fsync the directory.
4. One DB transaction: `Asset`, `Capture` (profile `voice_command`), `CaptureProcessing(pending, generation 1)`, `CaptureAsset`, `capture_revisions(created)`; `finish_action`; commit.
5. Any exception → rollback + unlink temp/final path (the same pattern as `upload`).

**Duplicate guard.** A non-archived voice capture with the same `sha256` created < 2 min ago → 409 `duplicate_recording` with the existing capture id (covers a lost key/blob after reload). Distinct from the idempotency key, which covers retries of one attempt.

**Proxy reconciliation (H20) — the minimal change.** Today the proxy calls `await req.arrayBuffer()` (whole body in Node memory) before contacting FastAPI, sets no length limit, and forwards only `content-type` and `Idempotency-Key`. So a backend-side preflight (capability, size, disk) **cannot** prevent the proxy from buffering the body first, and “raw streaming” is not what happens between browser and backend. Proposed compatible design — **bounded buffering, not streaming**:
- In `route.ts`, for `POST /voice-captures` only, enforce a **server-side body cap** (proxy env `TRACEBACK_VOICE_MAX_UPLOAD_BYTES`, default 10 MB, must be ≥ the backend cap; not a `NEXT_PUBLIC` value): if the request’s declared `Content-Length` exceeds the cap → respond 413 **before reading the body**; otherwise read `req.body` through a reader that counts bytes and aborts with 413 the moment the cap is exceeded, so memory is bounded at the cap (+ one chunk) regardless of what the client claims. Then forward the buffered bytes exactly as today.
- Also compare counted bytes with the `size` query value and return 400 on mismatch before calling the backend.
- All other routes keep today’s behavior. The existing unbounded buffering of `POST /assets` (up to 100 MB) is a **pre-existing limitation, not fixed by this plan**.
- Because the mutex allows one recording at a time, worst-case proxy memory for this path is ≈ 1 × the cap (per browser tab holding the lock; a second tab is refused by Web Locks).
- Low-disk protection is therefore two-layer: an **advisory** `low_disk` flag in `GET /capabilities` (the mic shows a warning before recording), and the **authoritative** backend preflight (step 1) which prevents a disk write but not the proxy’s bounded buffering.
- A streaming pass-through (`duplex: "half"` request body) is possible with Node’s fetch but changes error/replay semantics and is **not** part of v1.

**What this does not claim.** `POST /assets` remains non-idempotent [Confirmed] and unchanged for other uses.

**Crash windows.** Order is *file first, then DB commit*: (a) crash before commit → an orphan file with no `assets` row (invisible, wastes disk); (b) never the reverse. **The existing cleanup does not handle (a):** it unlinks only on exceptions caught in the same request, and `cleanup_pending` assets are retried only when the user re-issues the explicit delete [Confirmed]; `kill -9`/power loss skips both.

**Reconciler** `scripts/asset_reconcile.py` [Proposal]: dry-run by default; reports (1) files in `asset_dir` with no `assets` row older than 15 min, (2) stale `.upload-*` temp files, (3) `assets` rows whose file is missing, (4) `cleanup_pending` rows. `--apply` removes only (1)/(2) past the grace period and prints what it removed. The API runs it in **report-only** mode at startup (counts only, logged).

The frontend retains blob, key, sha256, `captured_at`, timezone until success. MCP’s typed voice capture uses `POST /captures` and has no asset.

### 9.1b Typed voice command

`POST /captures` with `source_type:"typed"`, `processing_profile:"voice_command"` (UI “Send as command”, MCP). No audio, no STT; the transcript is the immutable `raw_text`.

### 9.2 Transcript checkpoint — `POST /api/v1/captures/{id}/transcript` (processor-only)

Body: `{expected_generation, lease_token, transcript, language?, stt_model_id?, duration_ms?, no_speech: bool}`. It requires the same lease + generation as other processor calls. **It does not take or bump `expected_version` and writes no revision** (§5.1). It stores `capture_processing.transcript` only. `no_speech=true` → `failed` (`error_code="no_speech"`) through the normal failure path (bumps version, writes a `processing_failed` revision). **The processor calls it after STT succeeds and before Qwen.** For `voice_command`, `/fail` **preserves an existing checkpointed transcript when the request carries none** (H21) and never overwrites it with null. Not exposed through MCP (C14).

### 9.3 Proposal, accept, and override audit

- **`POST /captures/{id}/proposal`** accepts `NoteProposal | VoiceCommandSubmission` (§7.2); note behavior unchanged. The backend recomputes and stores the `CommandProposal` (§7.3–7.4). Submission validation includes stale lease/generation/version → 409, unknown fields → 422.
- **`POST /captures/{id}/proposal/accept`**: body `{expected_version, expected_generation, overrides?: {title?, content_md?, due_*?, destination?}, confirm_overdue?: bool}` (manual mode; `mode:"processor"` + lease only for auto-apply). **Concurrency fields here are new; they mirror `/interpretations`.** Requires a stored operation (`capture_only`/`ambiguous`/`unsupported` → 422 `nothing_to_accept`). Validates overrides with the same rules as `ItemCreate`/`TaskFields`, re-checks destination/target versions, applies the overdue-confirmation rule (§8.3), then calls the **same internal function** as `/interpretations`.
- **Voice content rule (H2).** For `voice_command`, `/interpretations` accepts exactly one create op (note or task) in Phases 1–3. Manual callers may supply any content the user chose (this is also the disabled-mode escape hatch); **processor-mode** accept is recomputed from evidence (§7.4).
- **Override audit (H19).** Every accepted voice operation — `/proposal/accept`, manual `/interpretations`, or processor auto-apply — writes the capture revision (`change_type="interpreted"`) with **server-computed** evidence: `proposal_present`, `proposal_generation`, `proposal_sha256`, `policy_version`, `accept_path ∈ {accept_endpoint, manual_interpretation, processor_auto}`, `accepted` (item_type, title, deadline fields, destination kind/id/version, `content_sha256`, `content_length`), `edited_fields` (diff of the stored proposal operation vs the submitted operation over `title`, `content`, `due_date`, `due_time`, `due_timezone`, `destination`, `item_type`, `intent`), and `overdue_confirmed`. With no stored proposal: `proposal_present:false`, `edited_fields:null`. Discarding an `awaiting_review` capture records `proposal_generation` and `discarded_after_proposal:true` in its archive revision.

### 9.4 Corrections

Extend `CaptureCorrectionCreate` with `transcript_text` (bounded, min 1), valid only for `voice_command` and **only while voice is enabled**. **Concurrency:** the route keeps its confirmed `expected_version`-only contract; the server bumps `generation` itself (as the note profile does [Confirmed]). **No `expected_generation` is added by default** — `version` is already bumped by every proposal/failure, so a correction sent against a stale proposal conflicts on `version`. *(If review finds a case where `version` alone is insufficient, adding an optional `expected_generation` to corrections would be a further **[Proposal]**, not assumed.)* Effect: generation++, proposal cleared, state → `pending`, requeued; the STT transcript is preserved in its revision evidence; re-processing skips Whisper when a corrected transcript exists. While voice is disabled, `transcript_text` returns 409 `capability_disabled` (it would strand the capture) and the UI uses the manual escape hatch (§10.1). Editing title/destination/deadline on the card is `overrides` on accept, not a correction.

### 9.5 Capability and policy source

**One authoritative source: backend settings loaded from the environment/`.env`** (the existing mechanism), read-only at runtime; the UI learns them from the backend.

- New `Settings` fields (env prefix `TRACEBACK_`), validated at startup (invalid → API refuses to start): `voice_commands_enabled: bool = false`; `voice_max_seconds = 60`; `voice_max_upload_bytes = 10 MB`; `voice_min_free_disk_bytes = 2 GB`; `voice_auto_apply_intents: str = ""` (CSV ⊆ {`create_task`}; anything else fails startup; **empty = auto-apply off**).
- **Restart behavior.** Changing a value requires stopping and restarting the manually-run API ([local development](../local-development.md)). Leases, generations, captures live in PostgreSQL and survive; processor calls simply see the new policy on their next backend call. **No runtime toggle endpoint and no settings table.**
- **Discovery.** `GET /api/v1/capabilities` (authenticated, read-only, `Cache-Control: no-store`): `{voice_commands: {enabled, accepts_audio, max_seconds, max_upload_bytes, accepted_mime_types, allowed_intents, auto_apply_intents, policy_version, low_disk}, queue: {pending_voice, oldest_pending_age_s}}`. The frontend fetches it on load and on every mic click; **no `NEXT_PUBLIC_*` flag is used**. Optional read-only MCP `get_capabilities`.
- **Enforcement (backend).** While disabled: creating a `voice_command` capture → 403; `claim-next` skips `voice_command` captures; `transcript_text` correction and `retry` of a voice capture → 409 `capability_disabled`; processor-mode accept refused. **Manual review, accept, save-as, manual interpretation, discard and archive continue to work** (C2).
- Processor settings (`TRACEBACK_PROCESSOR_*`) stay in the processor env; the processor never decides policy.

### 9.6 Storage helpers

`GET /api/v1/storage/summary` (read-only): asset directory bytes total and for voice audio, counts of voice captures by state/archived/source-linked, free disk. Used by the Archive/cleanup section and `capabilities.low_disk`.

### 9.7 Migrations

Expected: none for profile, transcript, proposal or audit (JSONB + free-string `change_type`). A possible index on `(processing.state, queued_at)` for `claim-next` is decided by measurement in Phase 1. No migration is assumed.

## 10. Failure, retry and stale-work fencing

**“Capture persists” is conditional.** Voice ingest fails safely (nothing half-saved) in each case below; only the in-memory retained blob survives, so the UI offers retry or **Save recording to a local file**.

| Case | Behavior |
|---|---|
| Microphone permission denied / no device | No recording, no capture; toast with instructions; typed command and manual forms available. |
| `MediaRecorder` missing or no supported MIME (`isTypeSupported` over the Phase 0-measured list) | Mic disabled with reason; typed command available. |
| Recording ends early (track `ended`, unplug, sleep) | Treated as Stop if ≥ 0.7 s with an “ended early” note; else discarded. |
| Tab/window closed or reload while recording/unsent | **Audio is lost** (no silent IndexedDB persistence of unsent audio in v1); `beforeunload` guard. Once the server acknowledged the capture, closing is safe. |
| Backend unreachable / 401 / proxy 503 | `failed_unsent`: blob, key, sha256 retained; Retry replays the identical request; “Save to file”. |
| Response lost after the server committed | Retry with the same key replays the recorded capture; if the key was lost, `duplicate_recording` (409) points at the existing capture. |
| Double-click / two tabs | Provider mutex + Web Locks; residual concurrent duplicates serialized by the advisory lock. |
| Upload too large (proxy 413 or backend 413), unsupported media (415), duration over cap | Rejected before any write; limit shown; nothing stored. |
| **Disk full / low disk** (asset dir) | Advisory `low_disk` warning before recording; backend pre-check (< `voice_min_free_disk_bytes`) → 507 before writing; `ENOSPC` mid-write → temp removed, rollback, 507. No row created. UI: “Not enough disk space” + link to storage cleanup. Manual forms still work. |
| PostgreSQL unavailable / DB disk full | 503; nothing committed; the file from step 3 is unlinked, or reaped by the reconciler if the process died. |
| Backend rejection (422, 403 `capability_disabled`) | Shown verbatim; retry disabled for non-retryable codes; blob retained until discarded. |
| Processor down / Ollama stopped | Capture `pending`; “Waiting for local processor” after 20 s; manual escape hatch (§10.1); nothing is deleted by timeout. |
| Whisper failure / `no_speech` / unsupported codec / too long | `failed` with a specific `error_code`, audio retained; Retry (generation++, only while enabled), Discard, or the escape hatch. |
| Qwen invalid JSON after bounded retries | `failed` (`InterpretationError`); transcript already checkpointed and preserved by `/fail`; Retry runs the LLM stage only. |
| Lease expiry mid-job | Late submissions rejected 409. |
| User acts while the processor runs | Manual action bumps generation → the processor’s later `/transcript`, `/proposal`, `/accept` gets 409 and is discarded (C10). |
| Two Accept clicks | Idempotency-Key + `expected_version` → one item, one 409. |
| Destination/target changed since proposal | 409; UI refetches, keeps user edits, re-renders. |
| Accepted after the deadline passed | 422 `overdue_confirmation_required` → explicit confirm (§8.3); never silent. |
| Retry storms | Retry needs `expected_generation`; UI disables in flight; bounded attempts (existing). |

### 10.1 Manual escape hatch (works with voice disabled, processor down, or transcript missing)

Disabling voice (or a stopped processor) can leave a `pending` capture with audio but no transcript. The escape hatch **depends on no worker and no requeue**:

1. In Inbox and on the card, a `pending`/`failed`/`awaiting_review` voice capture shows the audio player and, when voice is disabled or waiting > 20 s, **“Voice processing is off/unavailable — Type it instead”**.
2. **Type it instead** opens an inline editor where the user types the text (pre-filled with any existing transcript). It is **not** a `transcript_text` correction (which requeues to a worker that may be skipped).
3. The user then chooses **Save as note** or **Save as task** (with the title, deadline, and optional destination/container fields of the ordinary manual forms; “Open full form” reuses the `/tasks/new?…captureId=` pattern for tasks). The action is the existing **`POST /captures/{id}/interpretations`, `mode:"manual"`** [Confirmed route], accepted from `pending`/`failed`/`awaiting_review`, bumping `generation` (fencing any late processor call). Voice profile rule: one create op, any user-chosen content.
4. Existing proposals stay manually acceptable while disabled (`/proposal/accept`, manual mode; the overdue confirmation and audit still apply).
5. **Discard** (archive) and Keep in Inbox remain available.

These paths are audited like any manual acceptance (`accept_path: manual_interpretation`, `proposal_present` as applicable).

## 11. MCP parity and deliberate exclusions

| Capability | MCP | Rationale |
|---|---|---|
| Typed voice-command capture (`create_capture` with `processing_profile="voice_command"`, `source_type="typed"`) | **Yes** — extend the Literal/docstring; `entry_point="mcp_typed"` set by the adapter | Same pipeline without STT; main deterministic-test vector. 403 when disabled. |
| Read proposal/transcript/audio metadata (`get_capture`, `list_captures`, `get_asset`) | Yes, already | — |
| `accept_capture_proposal` → `/proposal/accept` (manual mode, incl. `confirm_overdue`) | **Yes** | Parity; avoids clients rebuilding operations. |
| `apply_capture_interpretation`, `retry_capture`, `correct_capture` (+ `transcript_text`), `archive_capture` | Yes / extend | Parity. |
| `get_capabilities` (read-only) | Optional yes | Discovery. |
| Audio ingest, `POST /assets` for audio | **Excluded** | No binary through MCP. |
| `/claim`, `/claim-next`, `/fail`, `/transcript`, processor-mode accept | **Excluded** | Lease tokens and model-output submission never reach MCP (C14). |
| Storage summary and destructive storage steps (asset/capture permanent delete already exist and keep their MCP `confirm` rules) | Existing destructive tools unchanged; **no new** storage tool | Confirmation must come from the user in the current turn. |
| Permanent deletion via voice | **Excluded everywhere** | — |

`mcp_typed` captures are review-first and **never auto-applied**.

## 12. Auto-apply vs review vs reject — decision matrix

The backend computes `disposition` **only from facts it derives itself** (§7.4). **Model confidence and every processor-supplied verdict are not inputs.** **Launch state: `voice_auto_apply_intents` is empty, so every “eligible” row is `review` until the §15 gate opens, the operator sets the env value and restarts the API.**

| Situation | Disposition | Notes |
|---|---|---|
| `create_task`; **explicit task/reminder word** (§8.5 rule 1); backend-derived lexicon agrees with model; title/spans grounded in the stored transcript; **no destination** and no surface-context destination; deadline none, or parsed with **no warnings** (not `next`, not same-weekday, not assumed year/meridiem/date/time, not numeric-ambiguous, not DST-gap, no `delayed_ingest`/`clock_ahead`, **and not in the past at accept time**); no flags; `entry_point ≠ mcp_typed`; `create_task ∈ voice_auto_apply_intents`; recomputation at accept equals the stored operation | **auto_apply_eligible** (Phase 6 only) | Appears in Tasks; undo = archive |
| Any deadline earlier than now at accept time | **review** (manual may confirm overdue); never auto-applied | §8.3 |
| `create_task` with a resolved project/folder destination | **review** until a destination-accuracy gate exists | Silent misfiling |
| `create_note`, any destination or none | **review** | C11 |
| `intent_inferred`, `intent_conflict`, or `ambiguous` intent | **review** (selector; nothing preselected for `ambiguous`) | §8.5 |
| `next <weekday>`, same-weekday, assumed/unresolved/past date, time already passed, numeric-ambiguous, DST gap, `delayed_ingest`, `clock_ahead` | **review** | §8.3 |
| Destination `ambiguous`, `not_found`, fuzzy/low, or `surface_context`-sourced | **review** | Never guessed |
| `self_correction`, `multi_intent`, `unclear_audio`, `ungrounded_text`, `possible_duplicate`, `unsupported_language` | **review** | Reasons shown |
| `capture_only` | **review** (`awaiting_review`; actions **Save as note / Save as task / Keep in Inbox / Discard**) | Never resolved without an item; the capture itself has no location |
| `move_item`, `complete_task`, `reopen_task`, `archive_item` (Phase 4) | **review always**; auto-apply never enabled | Exactly one active target + version |
| Intent outside `allowed_intents` | **reject** (`awaiting_review`, “restricted launcher”) | No write |
| `unsupported` intent (delete, restore others’ data, folder/project creation, relation edits, bulk ops, note-body edits, off-list) | **reject** (`awaiting_review`, reason) | No write |
| Transcript empty / `no_speech` | **failed** (`no_speech`), audio kept | Not a disposition |
| Submission validation failure (stale lease/generation/version, malformed slots, unknown fields) | HTTP 409/422; processor marks `failed` where applicable | Nothing bypasses validators |
| Disabled voice | Manual review/accept/save-as still allowed; processor-mode accept refused | §9.5 |

If model confidence is later measured as calibrated (Phase 5), it may become an *additional* hard requirement, never a sufficient condition, and would still not be displayed as product truth without evidence.

## 13. Privacy, local-only constraints, MacBook Air M5 resources, latency

**Privacy / local-only**

- All STT and LLM inference is on loopback (`whisper-cli` subprocess; Ollama on 127.0.0.1, enforced by `processor/config.py` [Confirmed]); no cloud fallback, no telemetry egress. A full network-off run is **not yet verified** (per local-models): Phase 0 and Phase 5 check.
- Audio and transcripts are personal data: only local PostgreSQL and the asset directory (covered by existing backup/restore); logs contain no transcript, audio path, titles, or destination names.
- The transcript is untrusted input to Qwen (prompt injection). Defenses: closed intent enum, no tools, slots-only output, backend recomputation, `requested_delete` → `unsupported`, review-first.
- Microphone: only on user gesture; permission belongs to the browser origin; tracks stopped on stop/cancel/unmount [current pattern Confirmed]; indicator always visible; no persistence of unsent audio beyond the tab; the in-memory blob is cleared on success/discard.

**MacBook Air M5 (16 GB, fanless).** Existing **synthetic** measurements, not a quality or sustained-load benchmark ([local models](../local-models.md)): Whisper small ≈ 0.5–0.8 s warm for ~5 s audio (≈ 14.5 s cold), child RSS ≈ 790 MB; `qwen3.5:4b` ≈ 2.5–5 s per short call, ≈ 3.3 GB resident, 100% GPU.

- **Strictly sequential**: one capture, one model at a time; Whisper exits before Qwen runs; no preemption of a running job. The backend policy recompute is cheap pure Python and runs in the API process, not in the model path.
- No claim beyond those numbers until Phase 0 measures the real chain (browser audio → ffmpeg → Whisper → Qwen → backend recompute).
- Ollama residency: default keep-alive keeps ~3.3 GB resident; evaluate 2–5 min keep-alive in Phase 0 against latency-after-idle and battery/thermal effect. **Safe default until measured: leave Ollama’s default.**
- Battery/thermal: measure on battery and after 20 consecutive commands. If macOS thermal state is serious/critical or Low Power Mode is on, the processor defers new jobs (captures stay `pending`, UI shows “Paused (system busy)”); captures still save. Never a bigger or cloud model.
- Storage growth is a resource too (§14.3). Alternative models only if Phase 0 fails the §15 gates.

### 13.4 Queue priority and perceived latency

Perceived latency = poll wait (up to 15 s today) + normalize + Whisper (+ cold start) + Qwen (+ model load) + backend recompute. Two bounded, backend-owned changes:

- **`POST /api/v1/captures/claim-next`** (processor-only, [Proposal]): the backend atomically **selects and claims** the next capture (the runner’s `list_pending_captures(limit=1)` is newest-first today). Rule: (1) skip `voice_command` captures while voice is disabled; (2) **aging first** — any pending capture waiting > 5 min is claimed before newer ones, oldest first; (3) otherwise `voice_command` is preferred over other profiles, but **at most 2 consecutive voice claims while an older non-voice capture waits**; (4) ties oldest-first (`queued_at`, `id`). No preemption; lease/generation semantics unchanged; returns 204 when idle. Claiming does not bump `version` (§5.1).
- **Adaptive polling (processor env, not policy):** 3 s while `capabilities.voice_commands.enabled`, else 15 s; fall back to 15 s if Phase 0 shows non-negligible idle cost. p95 “Stop → review card” is a §15 target, not a claim.

## 14. Persistence, provenance, telemetry, storage lifecycle

### 14.1 Persistence and provenance

- **Original evidence**: audio asset (sha256, size, MIME, `uploaded_at`) is immutable [Confirmed]; `created_at` is separate [Confirmed]. Current corrections can change `captured_at`, so **[Proposal]** voice ingest preserves the initially observed capture time in immutable source metadata and the `created` revision, while any manual correction records old/new values, bumps generation and keeps both. The transcript is an *interpretation artifact* on `capture_processing.transcript`; revisions record `proposal`, `processing_failed`, `correction`, `interpreted` (with the transcript evidence hash from §5.1) — what STT/Qwen said versus what the user accepted.
- **Provenance**: acceptance creates the item and an `item_sources` link (`link_kind="interpreted"`) [Confirmed]; item revisions record actor (`user` manual, `processor` auto-apply) and client label.
- **Undo**: create → archive (H9); Phase 4 mutations via the generic undo. The capture remains after undo.

### 14.2 Audit and local telemetry

- Override audit per §9.3 in `capture_revisions.changes` (server-diffed). Metrics — accept/edit/discard rates per intent, `edited_fields` histograms, time-to-review, retry counts, disposition vs outcome, overdue confirmations — come from PostgreSQL via an offline script (Phase 5) that imports the same `backend/voice_policy` package.
- Runtime counters: content-free JSON lines in the local processor/API logs: capture UUID, stage, latency_ms per stage, model tag, error_code, disposition, `policy_version`, RSS peak, thermal state. **Never** transcript, audio path, titles, destinations. Reuses existing error-body redaction. Nothing leaves the machine.

### 14.3 Storage lifecycle (archive-first; no side door)

Voice can accumulate sensitive audio. Order-of-magnitude estimate to be **measured** in Phase 0: a 10–30 s Opus clip ≈ 0.1–0.5 MB; ~20 commands/day ≈ 1–4 GB/year (the transient normalized WAV ≈ 1.9 MB/min is deleted after transcription).

**Reference rules [Confirmed]:** `capture_assets` is `RESTRICT`; an asset can be deleted only when archived and unreferenced; a capture can be deleted only when archived and unlinked from all items; archiving a capture or asset **does not** reclaim bytes; a resolved capture that produced an item has a source link, so reclaiming its audio requires the user to deliberately **unlink that source** (which loses that provenance link).

**v1 policy [Proposal]:**

- **No automatic deletion and no silent unlinking** (C6, C7). Retention is user-driven and visible.
- **Prevention:** disk guard (§9.1a, §10), `capabilities.low_disk`, mic warning banner at < 2× threshold.
- **Storage view** (Archive page section, `GET /storage/summary`): voice audio bytes/counts by state — active unresolved / resolved with source links / archived — oldest first with per-capture size.
- **Guided reclaim = a checklist that only calls existing routes, one explicit confirmed click each:** (1) archive the capture (existing); (2) for captures with **no source links**: `DELETE /captures/{id}?confirm=true` (existing; does not delete bytes), then `POST /assets/{id}/archive`, then `DELETE /assets/{id}?confirm=true` (existing; if it returns `cleanup_pending`, the guide offers to re-issue the same explicit delete); (3) for captures **with source links**, the guide shows “Linked to <item>: keeping audio” and points to the existing per-item Sources control; **it never unlinks on the user’s behalf**, and a user-initiated unlink first shows the provenance-loss warning. Backups keep independent retention; the dialog says so. UI-only; not exposed through MCP as a new tool.
- **Not in v1 (future product decision requiring explicit user approval):** an operation that deletes audio but keeps the capture/item (“discard audio, keep transcript”). It would be an irreversible exception to preserve-originals and archive-first, so it is **not designed, scheduled, or committed** here; if the user wants it, it needs a separate decision and plan.
- Reconciliation of orphan files: §9.1a.

## 15. Gated rollout and evaluation

Voice/STT is unbenchmarked, so **no phase after Phase 0 ships as “working” until its gate passes.** Gate numbers are *proposals*, set before running the benchmark and recorded with the results.

**Corpus (outside Git, user-recorded, real device)** — ≥ 150 utterances: the three seed patterns and variants (including each row of §8.5), dates (today/tomorrow/weekday incl. same-weekday and next weekday/absolute with and without year/numeric-ambiguous/none/past/time-already-passed/DST gap), delayed-ingest and clock-ahead simulations (synthetic `captured_at` vs receipt), duplicate-name destinations, non-existent destinations, category-only, self-corrections, multi-intent, unsupported/destructive, prompt-injection speech, generic “Add X in Y” with/without lexicon verbs, launcher-restriction cases, accented/fast/quiet speech, built-in mic vs headset, quiet vs noisy room, ≥ 20 no-speech/accidental clips. Each labeled with expected intent, title, content, destination *path*, and date/time under a fixed synthetic `captured_at`. A parallel typed corpus isolates STT from LLM error. Synthetic `say` clips seed regression only.

| Metric | Gate for review-first real use (Phase 3) | Gate to consider auto-apply (Phase 6) |
|---|---|---|
| Intent accuracy (typed corpus) | ≥ 95% | ≥ 98% on `create_task` with an explicit task/reminder word |
| Intent accuracy (audio corpus) | ≥ 90% | ≥ 95% same class |
| Title/content grounding-correct | ≥ 90% | ≥ 95% |
| Deadline (date+time+tz) exact match where a date is spoken | ≥ 90% | ≥ 97% on warning-free parses |
| Date/weekday/time-of-day parser tables (typed spans) | 100% of table cases | 100% |
| Destination top-1 exact ID where it exists | ≥ 90% | (destinations excluded initially) |
| False-positive writes (wrong item created that the user did not see first) | 0 by construction | 0 in ≥ 300 consecutive eligible trials |
| Unsupported/destructive/injection utterances reaching a write | 0 | 0 |
| Auto-applied captures re-transcribed offline vs stored transcript (audit) | n/a | no material disagreement on the audited sample |
| Processor-forged evidence (extra fields, forged flags/IDs) accepted | 0 | 0 |
| p95 Stop → review card (warm) | ≤ 15 s (target to test) | same |
| 20 consecutive commands | no swap pressure; RSS within measured budget; thermal recorded | same |
| Disk-full / kill-mid-upload drills | no orphan rows; reconciler reports files | same |

Failure stops the phase; options are prompt/schema tuning, a different quantization/model, or narrowing supported utterances — never loosening validation or adding a cloud model.

## 16. Test plan

**Deterministic (no model, no microphone) — tests import `backend/voice_policy` directly**

- *Dates/timestamps*: full §8.3 tables; **Friday-on-Friday** and “this/next Friday” across every weekday of the anchor; Monday-start-week boundaries; month/year rollover; year assumption > 90 d; numeric ambiguity; ordinals/spoken numbers; meridiem/noon/midnight; **time-of-day interactions** (“today at 9 AM” at 10:14, time-only rollover, “tonight”); DST gap/fold in the four zones; **`delayed_ingest` and `clock_ahead` with `captured_at` preserved and both timestamps in the proposal; alternative under the receipt anchor; anchor never replaced**; verbatim-span grounding.
- Destination resolver (exact, leaf, category alias, duplicates, archived, fuzzy, project/folder qualifier); intent policy (every §8.5 rule/example, conflicts, restriction); disposition (every §12 row; **assert model confidence, model flags removal, and processor-supplied verdicts change nothing**).
- Schema: extra/forbidden submission fields rejected 422; model-emitted IDs/ISO dates rejected; spans not in the transcript dropped.

**PostgreSQL-backed API tests (real Postgres, throwaway DB, never live data)**

- **Ingest atomicity/idempotency**: same key + same bytes → one asset, one capture; same key + different payload → 409; 20 concurrent same-key requests → one capture; lost-response retry → replay; digest/size mismatch, oversize, unsupported MIME → nothing persisted, no file; `Content-Length` absent or equal to `size` accepted, unequal rejected; ENOSPC (patched write) and low-disk pre-check → 507, no row/temp; DB error after `os.replace` → file unlinked; simulated crash between replace and commit → reconciler dry run lists the orphan and `--apply` removes it only after the grace period; duplicate sha256 < 2 min → 409 with the existing capture id; legacy `POST /assets` unchanged.
- **Capabilities/policy**: env defaults (disabled, empty auto-apply); invalid `voice_auto_apply_intents` fails startup; disabled → voice `POST` 403, `claim-next` skips, `transcript_text` correction 409, retry 409, **manual interpretation/accept/discard still succeed**; `GET /capabilities` matches settings and is `no-store`.
- **Trust boundary**: a submission with processor-asserted `warnings`/`flags`/`destination_id`/`due_date`/`disposition`/`grounded` → 422; forged model flags cannot remove backend flags; hallucinated span not in the transcript → dropped + `ungrounded_text`; **auto-apply recomputation**: proposal stored, then catalog changed (destination archived/renamed) or `now` moves past the deadline or the env policy is emptied before processor-mode accept → 409 `proposal_stale`/`policy_changed` and the capture stays `awaiting_review`; typed voice capture recomputes from immutable `raw_text`; recomputed operation ≠ stored → refused.
- **Version mechanics**: transcript checkpoint leaves `Capture.version` unchanged and writes no revision; `/proposal` after checkpoint succeeds using the version read after `/claim`; a UI-held version stays valid across the checkpoint; proposal/fail/retry/correction/archive/interpretation each bump exactly once with unique `resulting_version`; `/fail` preserves the checkpointed transcript; 409 `details` carry `version`, `generation`, `state`, `proposal_sha256`; correction against a stale proposal conflicts on `version`.
- **Overdue semantics**: accept of a past deadline without `confirm_overdue` → 422 `overdue_confirmation_required`; with it → created and audited; **manual `/interpretations`/`POST /items` with a past deadline unchanged**; date-only *today* not overdue; processor-mode accept with a past deadline → never eligible.
- **Lifecycle**: `capture_only`/`ambiguous`/`unsupported` stay `awaiting_review` and appear in `GET /inbox`; `/proposal/accept` on them → 422 `nothing_to_accept`; “Save as note/task” via manual interpretation resolves once; a capture never reaches `resolved` without an item; archive of an awaiting-review capture records the discard revision; no test or route treats a capture as having a folder.
- **Disabled-mode escape hatch**: `pending` voice capture with audio and no transcript while voice is disabled → manual interpretation (note and task) succeeds, generation bumps, a late processor call gets 409; existing proposal manually accepted while disabled.
- Accept: exactly one item; atomic container placement; source link; generation bump; overrides validated; double accept → one 409; stale versions → no partial write. **Override audit**: no edit → `edited_fields=[]`; each edited field recorded; no-proposal → `proposal_present:false`; client cannot forge `edited_fields`; `content_sha256` matches; `overdue_confirmed` recorded.
- **`claim-next` fairness**: aging beats newer captures after 5 min; ≤ 2 consecutive voice claims while an older non-voice capture waits; disabled voice skipped; no double claim under concurrent callers; empty → 204; no version bump.
- **Legacy freeze**: `general` audio no longer auto-interprets (transcript checkpointed via `/fail`, `legacy_audio_requires_review`); typed `general` and `task_quick_add` unchanged.
- **Storage**: reclaim checklist uses only existing routes; capture with source links cannot be deleted and the guide never unlinks; asset delete refused until archived and unreferenced; `cleanup_pending` re-issue works; `GET /storage/summary` counts.
- Privacy: log-capture test asserting no transcript/title/destination in logs or error bodies.

**Processor tests (stubbed Ollama/Whisper/ffmpeg)** — stage order (transcript checkpoint before LLM); LLM-only retry reuses the transcript; processor sends **only** the slots/stt/model_confidence fields; lease expiry; late responses lose; malformed/adversarial output fails safe; injection transcripts yield `unsupported`; one job at a time; thermal/low-power deferral (injected); ffmpeg timeout/failure → specific `error_code`; adaptive polling. Real-model tests optional and skipped when unavailable.

**Proxy tests (Vitest, route handler with a mocked upstream `fetch`)** — declared `Content-Length` above the cap → 413 and **upstream never called, body not read**; no/lying `Content-Length` with an oversized stream → aborted at the cap (bytes read ≤ cap + one chunk), 413, upstream not called; body at exactly the cap accepted; counted bytes ≠ `size` query → 400; forwarded request preserves bytes exactly (compare sha256), query string, `Idempotency-Key`, content-type; backend 507/415/409 passed through unchanged; non-voice routes unchanged (regression, including that `POST /assets` still buffers as today); no `NEXT_PUBLIC` value read.

**Frontend tests (Vitest, mocked API)**

- Provider state machine: permission denied, unsupported MIME, start/stop/cancel, auto-stop at 60 s, < 0.7 s discard, track cleanup on unmount, no network before Stop, `beforeunload` guard, route change does not kill an active recording.
- **Mutex**: a second launcher click during `recording`/`uploading`/`failed_unsent` starts nothing and focuses the active recorder; Web Locks second-tab refusal; `failed_unsent` blocks new recordings until retry/save-to-file/discard; double-click yields one request.
- Retry replays the identical key/sha256/blob; “Save to file” exports the retained blob; capability disabled → mic disabled with tooltip, **no legacy path rendered**, escape-hatch “Type it instead” shown for stranded pending captures; capability polled on load and on click.
- Review card for every proposal kind including `capture_only`/`ambiguous`/restricted-launcher; **`capture_only` shows Save as note / Save as task / Keep in Inbox / Discard and no raw-capture “Choose location”**; destination picker appears only inside Save-as; overdue confirmation dialog; both timestamps shown for `delayed_ingest`; date alternative chips; **no confidence label rendered anywhere**; 409 refetch keeps user edits and silently resubmits only when generation/proposal hash unchanged; Inbox “Needs review” badge; “task with deadline” (never “Reminder”); no Today; Other not Everyday Life; keyboard operation.
- Entry-point matrix: global, Tasks (restricted), notes (restricted), project/folder/category (hint only), Inbox row.

**MCP tests** — typed voice capture forwards profile/`entry_point`; disabled → 403 surfaced; `accept_capture_proposal` forwards versions/generation and `confirm_overdue`, surfaces 409/422; processor-only tools and audio ingest unregistered; `mcp_typed` never auto-applied.

**Real-device tests (recorded in [backend-validation](../backend-validation.md))** — Chromium and Safari recordings → normalization → transcript and the measured MIME list; §15 corpus on built-in mic and headset, warm/cold, battery/plugged; network-off end-to-end; 20-command thermal run; memory/swap; accidental-activation drills; offline-model drills (stop Ollama, stop processor, kill during Whisper/Qwen, restart mid-lease); **kill -9 the API mid-upload (no visible row; reconciler-visible orphan); fill a scratch volume (507); send an oversize body through the real Next proxy and watch its memory; toggle env, restart, confirm the UI follows `/capabilities`; disable voice with a `pending` capture and complete it through the escape hatch.**

## 17. Threat and failure-case enumeration

| # | Threat / failure | Mitigation |
|---|---|---|
| T1 | Prompt injection via speech | Closed intent enum; no tools/SQL; slots-only inert JSON; backend recompute; deletion/restore/bulk are `unsupported`; review-first |
| T2 | Hallucinated IDs | Model and processor emit no IDs; backend resolver over the live catalog; re-validated at accept |
| T3 | Misheard destination silently misfiles | Fuzzy = review; breadcrumb shown; no destination auto-apply at launch |
| T4 | Wrong date (same-weekday, “next Friday”, time already passed, locale, year, DST) | Backend deterministic parser from verbatim spans; ambiguity/assumption → review; alternatives shown |
| T5 | Model-calculated date trusted | Model has no date fields; only spans; grounding check; one parser |
| T6 | **Anchor silently replaced / timestamps conflated** | `captured_at` immutable anchor; `created_at` separate; skew flags force review and show both; alternatives, never substitution |
| T7 | **Processor-forged evidence drives auto-apply** | Submission `extra="forbid"`; backend derives all facts; auto-apply recomputes from stored evidence, current catalog/time/policy; residual STT-transcript trust stated and audited offline |
| T8 | Duplicate items/assets (double click, retries, MCP replays, lost response) | One-request ingest + idempotency key + advisory lock + sha256 guard; accept idempotency; `expected_version` |
| T9 | Orphaned bytes after crash/lost response | File-then-commit, exception unlink, reconciler with grace period; existing cleanup not claimed to cover it |
| T10 | Proxy memory exhaustion by oversize/lying uploads | Bounded proxy read (cap + one chunk), 413 before/at cap, single-recording mutex; pre-existing unbounded `POST /assets` buffering acknowledged, unchanged |
| T11 | Stale automation overwrites manual work | Generation+lease fencing on transcript/proposal/accept/claim-next; manual actions bump generation |
| T12 | **False version conflicts from internal stages** | Transcript checkpoint and claims do not bump `version`; only user-visible transitions do; 409 details enable safe refetch |
| T13 | Accidental recording / ambient speech | Click-only, no shortcut/wake word, indicator, 60 s cap, no-speech gate, mutex, discard = archive, `beforeunload` |
| T14 | Two recorders | Provider mutex + Web Locks; `failed_unsent` blocks new recording |
| T15 | Sensitive audio leaves the machine | Loopback-only; no cloud fallback; network-off verification; content-free logs |
| T16 | Audio accumulates / disk fills | Disk guard (advisory + authoritative), storage view, archive-first guided reclaim; no auto-delete |
| T17 | **Irreversible audio deletion or silent provenance loss** | No audio-discard shortcut in v1; reclaim only via existing archive-first, confirmed routes; guide never unlinks sources |
| T18 | Resource exhaustion/throttling | Sequential single job; bounded audio/output/context; thermal/low-power deferral |
| T19 | Model/processor unavailable | Capture-first; `pending`; “waiting” UI; **manual escape hatch independent of workers** |
| T20 | **Stranded pending audio when voice is disabled** | Escape hatch via manual interpretation; `transcript_text`/retry refused (409) rather than requeueing to a skipped worker; existing proposals manually acceptable |
| T21 | Lease-token leakage | Processor routes not in MCP; tokens never in `GET`; redaction |
| T22 | Undo confusion / data loss | Archive-first; capture retained; no voice permanent delete |
| T23 | Silent partial writes | Single interpretation transaction; whole-batch rollback |
| T24 | Untrusted audio reaching ffmpeg/whisper | Size/duration caps, MIME detection, fixed argv, temp cleanup, timeouts |
| T25 | Multi-intent executed partially | `multi_intent` → review; confirmed split in Phase 4 |
| T26 | Misleading “reminder” promise | Copy says “task with deadline” |
| T27 | Cross-origin/browser abuse | Bearer token stays in the server-side proxy; CORS allow-list; no `NEXT_PUBLIC` secrets; capabilities authenticated |
| T28 | Policy drift / client flag mismatch | Single backend env source; startup validation; UI reads `/capabilities`; backend enforces every path; `policy_version` on proposals |
| T29 | Unsafe rollback to legacy auto-interpreting mic | Legacy mic UI retired; disabled mic is disabled; backend `general` audio frozen to review |
| T30 | `capture_only` items lost/hidden or mistaken for placeable | `awaiting_review` in Inbox with badge; actions place only created items |
| T31 | Wrong-intent generic “Add X in Y” | §8.5 lexicon + force-review + selector; surface context = restriction/hint |
| T32 | Queue starvation | Backend `claim-next` with aging and bounded voice preference |
| T33 | Unmeasurable quality | Server-diffed override audit incl. overdue confirmation |
| T34 | **Uncalibrated confidence treated as truth** | Stored for evaluation only; not rendered; not a policy input |
| T35 | Time-of-check/time-of-use | Locks + version checks at commit; recompute at accept |
| T36 | Model output too long/malformed | Bounded tokens/retries; `extra="forbid"`; durable `failed` |

## 18. Rollout, disable, and rollback

- **Authority**: `TRACEBACK_VOICE_COMMANDS_ENABLED` (backend env, §9.5); the UI follows `GET /capabilities`.
- **Legacy mic: retired.** In Phase 3 no UI control creates `general` audio captures. The backend `general` audio path is **frozen in Phase 1**: transcribe, checkpoint the transcript via the existing `/fail` `transcript` field, fail with `legacy_audio_requires_review` for manual resolution — never auto-interpreted again. Already-pending `general` audio captures are handled the same way. Typed `general` capture behavior and Tasks quick add are **unchanged** and **separately reviewed** (H5 note).
- **Disabled behavior** (flag off, `capabilities` unreachable, older backend): the command mic is **disabled with a reason**; typed capture, manual forms, review/accept of stored proposals, **the “Type it instead” escape hatch (§10.1)**, discard, and the guided storage reclaim remain available. No mic path falls back to the legacy capture.
- **Rollout order**: (1) Phase 0 measurement only; (2) typed voice path via MCP/dev on a scratch environment; (3) audio review-first, enabled by env on the daily-use install after a verified backup; (4) organization intents (review-only); (5) optional narrow auto-apply after the gate.
- **Rollback**: set `TRACEBACK_VOICE_COMMANDS_ENABLED=false` and `TRACEBACK_VOICE_AUTO_APPLY_INTENTS=` (empty), stop and restart the API. Effects: new voice captures refused (403); `claim-next` skips voice captures; processor-mode accept impossible; `transcript_text`/retry refused (409). **Stranded `pending`/`failed` voice captures stay in Inbox with audio (+ transcript if any) and are completed by the manual escape hatch**; `awaiting_review` proposals stay manually acceptable. No data migration to undo. Auto-apply is off instantly because eligibility is recomputed at accept. A bug in the ingest path is handled by the disabled mic, not the old path.
- **Backups**: run the existing verified backup before enabling Phase 3 and Phase 6.

## 19. Out of scope

Wake word / always-on/background listening; global OS hotkeys and (in v1) any recording keyboard shortcut; cloud STT/LLM or any cloud fallback; browser-native SpeechRecognition and any synchronous browser STT; streaming/partial-transcript UI; streaming pass-through of uploads through the Next proxy (v1 uses bounded buffering); fixing the pre-existing unbounded proxy buffering of `POST /assets`; speaker identification; reminders, notifications, recurrence; Today view or planned dates; automatic folder/project creation; permanent deletion, restore of others’ items, relation edits, bulk operations, note-body edits by voice; **any automatic deletion or retention expiry of audio; any “discard audio but keep capture/item” operation, and any silent unlinking of provenance** (a future explicit product decision requiring user approval, not part of this plan); personal-memory extraction ([personal memory plan](../personal-memory-plan.md)); semantic search; mobile UI; making generic capture interpretation undoable (H9 backlog); reviewing auto-apply of typed `general` captures and Tasks quick add (H5, separate); multi-user/auth; changing the model family before evaluation says so; a runtime-writable settings store; displaying model confidence to the user.

## 20. Phased delivery and acceptance criteria

**Phase 0 — Measurement spike (no product changes)**
Scope: browser recording formats (Chromium/Safari) → `file --mime-type` labels → ffmpeg normalize → whisper-cli on this Mac (H3); measured accepted-MIME list, clip sizes (storage estimate); network-off end-to-end; cold/warm/thermal/memory of the real chain; corpus recorded and labeled; baseline Qwen slot extraction on the typed corpus with a throwaway script; idle poll cost at 3 s vs 15 s; Ollama keep-alive options; **Next proxy memory behavior with a 10 MB body**.
Acceptance: results recorded in `docs/backend-validation.md` or a linked note; go/no-go per §15 rows; decisions on MIME list, keep-alive, poll interval.

**Phase 1 — Backend contract, policy package, durability**
Scope: `backend/voice_policy/` pure package (grounding, intent policy, dates/timestamps, destination resolver, disposition) with its tables; `voice_command` profile; **atomic idempotent `POST /voice-captures`** + reconciler; **the bounded proxy change**; `capabilities` + env settings with startup validation; transcript checkpoint (no version bump) and `/fail` transcript preservation; correction `transcript_text`; `VoiceCommandSubmission` recompute in `/proposal`; `/proposal/accept` with overdue confirmation; override audit; `claim-next`; storage summary; legacy `general` audio freeze; API docs updated.
Acceptance: pure-module tables 100%; all backend/PostgreSQL and proxy tests in §16 pass; note/task profile tests unchanged and green; `capture_only` stays `awaiting_review` and visible in `GET /inbox`; forged-evidence tests pass; no processor change required (fixtures submit slots).

**Phase 2 — Processor pipeline (typed first, then audio)**
Scope: `claim-next` client; normalization; transcript checkpoint before LLM; slot prompt + strict schema; **slots-only submission (no policy code in the processor)**; injection tests; sequential job; keep-alive/thermal/poll per Phase 0.
Acceptance: processor tests pass; real-model tests skip cleanly when unavailable; typed corpus meets the Phase 3 gate on real Qwen (scored by the backend package); LLM-only retry proven; late-response fencing proven; no log line contains content.

**Phase 3 — UI review-first (audio), enabled by env**
Scope: `VoiceCommandProvider` + launchers + `CommandReviewCard` (global, Tasks, notes, project/folder/category, Inbox); mutex/Web Locks; retained-blob retry and save-to-file; capability-driven disabled mic; **manual escape hatch**; **retire the legacy mic path**; states (waiting/failed/no_speech/needs review); overdue confirmation; timestamp display; undo-by-archive; storage view and guided archive-first reclaim; Skills label from `capabilities`.
Acceptance: frontend tests in §16 pass; typecheck/lint/build pass; audio corpus meets the gate on the real device; accidental-activation, disk-full, kill-mid-upload, env-toggle and disabled-with-pending drills pass; a week of daily use with logged outcomes and zero unintended writes.

**Phase 4 — MCP parity and organization intents (review-only)**
Scope: MCP typed profile + `accept_capture_proposal` + `get_capabilities`; `move_item`, `complete_task`, `reopen_task`, `archive_item` with unique-target resolution in the backend package; user-confirmed multi-intent split (create-only, ≤ 3, atomic); docs in `mcp-adapter.md`/`mcp-tool-reference.md`.
Acceptance: MCP tests pass; ambiguous/missing targets never write; generic undo verified for moves/completion; all writes remain review-only.

**Phase 5 — Evaluation report and hardening**
Scope: offline metrics script (override audit) using the shared package; full real-device corpus and 20-command thermal run; network-off proof; privacy log test; decide on keyboard shortcut, fast-path, model-confidence calibration.
Acceptance: §15 metrics recorded; decisions recorded (keep models, tune, or narrow); backups verified.

**Phase 6 — Optional narrow auto-apply (off by default)**
Scope: operator sets `TRACEBACK_VOICE_AUTO_APPLY_INTENTS=create_task` and restarts; processor-mode accept with backend recomputation for the §12 first row only; offline re-transcription audit script.
Acceptance: Phase 6 gate column met and recorded; rollback drill (env → empty + restart) verified; no auto-apply for notes, destinations, organization intents, inferred intents, past deadlines, skewed/delayed captures, or `mcp_typed`; model confidence remains non-sufficient and unrendered.

## 21. Prioritized implementation sequence

1. **Phase 0 measurements** (formats/normalization, network-off, latency/memory/thermal, storage estimate, proxy memory, baseline).
2. **`backend/voice_policy/` pure package with its tables** — the single home of every deterministic rule; independent of model, UI and DB, and the source of every safety guarantee (dates, timestamps, grounding, intent, destination, disposition).
3. **Backend Phase 1** in order: capabilities/env settings → atomic idempotent ingest + bounded proxy change + reconciler → transcript checkpoint (no version bump) + `/fail` preservation → proposal recompute + audit → accept endpoint with overdue confirmation → `claim-next` → legacy audio freeze → storage summary; each with PostgreSQL/proxy tests.
4. **Processor Phase 2**: typed transcripts first (MCP-drivable), then audio normalization + Whisper.
5. **MCP typed profile + `accept_capture_proposal`** early (cheapest end-to-end harness), then **Phase 3 UI** review-first including the escape hatch.
6. **Real-device evaluation and a week of review-first daily use** before anything further.
7. **Organization intents and multi-intent splitting** (review-only).
8. **Hardening and the evaluation report**; only then **decide** on narrow auto-apply — the default answer stays “review”.

## 22. Decisions taken (previously open)

- Feature switch: backend env `TRACEBACK_VOICE_COMMANDS_ENABLED` + `GET /capabilities`; no `NEXT_PUBLIC` flag, no writable settings store.
- Policy ownership: one backend-owned pure package, recomputed from stored evidence; the processor supplies slots only.
- Timestamps: `captured_at` anchor, `created_at` preserved, skew → review with alternatives.
- Past deadlines: allowed manually with explicit confirmation; never auto-applied; no global ban.
- Proxy: bounded buffering with a per-route cap for voice ingest; no streaming pass-through in v1.
- Transcript checkpoint: no version bump, no revision; evidence recorded in the next revision.
- Recording shortcut: none in v1. `transcript_text`: new correction field; no `expected_generation` added to corrections unless a concrete need appears.
- Ollama keep-alive: default until Phase 0; poll: 3 s while enabled with a 15 s fallback.
- Legacy mic: retired from the UI; backend general audio frozen to review.
- Audio reclaim: archive-first only; audio-discard shortcut is out of scope pending an explicit user decision.

Remaining measurement-dependent values (accepted MIME list, exact voice upload cap, keep-alive) have the safe defaults stated above and are confirmed in Phase 0; none changes the architecture.
