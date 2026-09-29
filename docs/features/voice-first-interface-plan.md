# Voice as the primary keyboard-free interface — independent implementation plan

Analysis only. No repository files were edited, no migrations run, no code written. Read: `docs/features/voice-command-capabilities-plan.md` (802 lines, rev. 3), `docs/features/voice-commands.md` (implemented slice), `docs/current-status.md`, `backend/voice.py`, `backend/voice_service.py`, `backend/voice_policy/{dates,destinations,intent,policy,text}.py`, `frontend/src/components/voice/*`, `frontend/src/lib/voice.ts`, `processor/voice.py`, plus the backend/frontend/processor files the existing plan cites.

## 0. Relationship to the existing plan, and where I disagree

The existing plan (call it **VCP-v3**) is unusually rigorous — trust boundary, version/generation/lease fencing, deterministic date parsing, archive-first storage — and I build on all of it rather than re-deriving it. Reused verbatim: capture-first persistence, backend-owned `voice_policy` package, strict processor slot schema, `disposition ∈ {review, reject, auto_apply_eligible}`, override audit, gated rollout methodology. This plan's job is the part VCP-v3 deliberately left out: **making voice cover the entire action surface**, and the **system-wide macOS shortcut** VCP-v3 put out of scope. Where I depart from VCP-v3, I say so explicitly:

1. **"No recording shortcut in v1" is the wrong call once voice is the primary interface.** VCP-v3's own §13 rationale (privacy, accidental activation) is real but the task requires a system-wide shortcut. I keep VCP-v3's mitigations (visible indicator, no wake word, 60 s cap, discard-first) but add a shortcut as a **native macOS helper**, not a browser feature (browsers cannot register global hotkeys or run while unfocused). This is a new component, not a UI tweak — see §7.
2. **Read/search/navigation by voice is entirely absent from VCP-v3** (it only ever produces a create proposal or nothing). A keyboard-free interface needs a **query intent class** that never writes and returns immediately, bypassing the review-card/proposal machinery altogether. This is additive, not a modification of VCP-v3's write path — see §3.
3. **VCP-v3's Phase 4 "organization intents" (move/complete/reopen/archive) are review-only forever in that plan, and multi-intent is capped at "≤3 create-only, atomic."** For voice to replace the keyboard, users need to also **edit content** (rename, append, change deadline), **link/unlink relationships**, **restore from archive**, **bulk-act on a listed set**, and chain **dependent multi-step commands** ("create a project called X, then add three notes into it"). VCP-v3 doesn't design any of this. I do, in §4–§6, reusing its trust boundary and version fencing exactly.
4. **Permanent deletion by voice**: VCP-v3 excludes it "everywhere," full stop. I keep that as the default and do not reverse it — but I add one narrow, gated exception (§4.6) because the task explicitly asks for "permanent deletion" in the covered-actions list. I flag this as the single point where I'd push back if asked: voice-triggered permanent deletion is the one operation class where a misrecognized word ("delete" vs "leave it") has no undo, and I recommend the default stay **voice-initiated, keyboard/pointer-confirmed** rather than fully voice-only, even though the task asks for keyboard-free coverage. See §4.6 and the disagreement callout there.
5. **Confirmation model**: VCP-v3's confirmation is "the review card" for creates. For edits/deletes/bulk ops that touch *existing* data, a proposal card with a diff view is not enough on its own for irreversible operations — I add **exact-phrase voice confirmation** for irreversible steps (§6.3), because a user who cannot reach a keyboard also cannot always look at a screen (e.g., driving, hands full), and "keyboard-free" should mean the confirmation loop itself works by voice, not that confirmation is skipped.
6. **Ambiguity handling**: VCP-v3 resolves ambiguity by showing a selector in the UI and stopping. That's correct for the reviewed-write path but breaks "keyboard-free" when the user has no way to disambiguate except by speaking again. I add a **voice disambiguation turn** (§6.4): the system reads back the candidates and lets a short follow-up utterance pick one, still inside the same operation-plan transaction.

Everything else — no cloud, no SQL/tools for the model, backend-owned dates/destinations, `expected_version`/`expected_generation`/lease fencing, archive-first, audit trail — is adopted unchanged.

## 1. Goal

Every action reachable today by mouse/keyboard in the Traceback desktop UI must be reachable by voice, with:
- **Immediate, read-only actions** (search, read, navigate) executing with no proposal and no confirmation — voice is just a faster query surface.
- **Reversible mutations** (create, edit, move, link, complete/reopen, archive) going through a proposal → review (voice or screen) → accept transaction, exactly like VCP-v3's create path, generalized to every item type and operation.
- **Irreversible mutations** (permanent delete, unlink that drops the last provenance source) requiring an **exact confirmation phrase**, spoken back by the user, verified against the transcript before the backend accepts it — never inferred from tone or a single "yes."
- A **system-wide macOS recording shortcut** (push-to-talk and toggle/accessibility modes), independent of which app has focus, that talks to the same local backend the browser uses.
- Full backend authority, local-only Whisper/Ollama, no new trust boundary: the model still emits inert slots; the backend still owns every ID, date, and disposition.

## 2. Action taxonomy (drives everything else)

| Class | Examples | Confirmation | Undo |
|---|---|---|---|
| **Read-only** | search, list inbox/tasks, read a note aloud, "what's due this week", navigate to a project | none — executes immediately | n/a (nothing changed) |
| **Reversible create** | note, task, project, folder | proposal → accept (voice or screen) | archive the created item |
| **Reversible edit** | rename, append, edit content, change deadline, move, link/unlink relation | proposal (diff) → accept | generic undo (`/actions/{id}/undo`) |
| **Reversible state change** | complete/reopen task, archive/restore item or asset | proposal → accept (can be same-turn confirm for low-risk cases, §6.2) | generic undo |
| **Bulk** | "archive all inbox notes older than a month", "complete all tasks in Kitchen renovation" | proposal listing every affected item id + a count → accept | generic undo per item (batch undo token) |
| **Irreversible** | permanent delete, unlink last source | proposal → **exact spoken confirmation phrase** → accept | none — this is why it's gated harder |
| **Multi-step / dependent** | "create a project called Kitchen renovation and add three notes: X, Y, Z" | one **operation plan** with ordered steps and explicit dependencies → single review → all-or-nothing accept | archive the whole plan's created items (one undo token covers the batch) |
| **Correction / meta** | "no, put it in Learning instead", "undo that", "read that back", "cancel" | acts on the *last* proposal or *last* action in this voice session only | n/a |

This taxonomy is the backbone of the operation-plan schema in §5 and the disposition table in §6.

## 3. Read-only voice actions (new — VCP-v3 has none of this)

These never create a `CommandProposal` and never touch the mutation path. They map to a new processor-side intent class, `query`, whose slots are answered **entirely by the backend** over existing read endpoints (`GET /items`, `/tasks`, `/inbox`, `/locations`, search) — the model's job is only to classify "this is a question" and extract a query span, never to compute the answer.

**Example utterances → backend call → spoken/read response:**
- "What's on my task list for this week?" → `GET /tasks?...` filtered/sorted by the existing overdue/upcoming rules → TTS or on-screen list, read back in order.
- "Read me the note called Normal forms." → `search_items`/`get_item` exact/leaf match (reuse the §8.4 destination resolver's matching tiers) → read `content_md` aloud (plain-text rendering, code fences skipped or announced).
- "Is anything overdue?" → count + list of overdue tasks.
- "What's in my inbox?" → `GET /inbox` summary count + first N items.
- "Go to the Kitchen renovation project." → pure navigation, front-end route change, no backend write; still resolved through the same deterministic destination resolver as §8.4 of VCP-v3 so "go to" and "add to" share one resolution implementation.
- "Search for vendor comparison." → keyword search (existing capability), results read back with index numbers so a follow-up ("open the second one") can refer to them without new destination phrases.

**Design decisions:**
- Query intent never produces a `CommandProposal` row and is **exempt from generation/version fencing** — it's a snapshot read, and staleness only means "ask again."
- A read-aloud response requires **local TTS**. VCP-v3 has no TTS component; this plan adds one (§7.3): a local, offline TTS engine (macOS `NSSpeechSynthesizer`/`AVSpeechSynthesizer` via the native helper, or a bundled offline TTS model — recommend the OS-native synthesizer first since it's already local, zero-install, and license-free, revisited only if quality is inadequate) — this keeps "local-only" intact; no cloud TTS API.
- Ambiguous reads ("read me the note" with 3 notes matching) reuse the same voice-disambiguation turn as §6.4, not a special read-only variant.
- Because read-only actions are the majority of "keyboard-free" usage (most of a day is reading/searching, not creating), they should ship **before** the broader write coverage — this is reflected in the phase order (§9): P0 includes query intent, not just the shortcut.

## 4. Write coverage — closing every gap VCP-v3 left as "unsupported"

All of the following reuse VCP-v3's machinery: processor emits verbatim spans + a closed intent enum (extended below), the backend `voice_policy` package derives every ID/date/version, `CommandProposal` stores the computed operation(s), accept is version/generation-fenced, undo is archive (or generic undo for edits/moves/state changes).

### 4.1 Create: notes, tasks — unchanged from VCP-v3.

### 4.2 Create: projects and folders (new)

VCP-v3 explicitly excludes this ("voice never creates folders", C11-derived). For full keyboard-free coverage this must exist, gated harder than note/task creation because a wrong project name pollutes the catalog others resolve against.

- New intent `create_container` with `container_type ∈ {project, folder}`, `name` (verbatim span), optional `parent_phrase` (folder-in-project or nested folder).
- Backend duplicate-name check against the live catalog (same resolver as §8.4): an exact or near-duplicate name **forces review** with the existing container shown ("A project named 'Kitchen renovation' already exists — create another with the same name, or add to that one?").
- **Never auto-applied** (matches VCP-v3's own auto-apply conservatism) — container creation is rare and each one reshapes the destination catalog every other command resolves against, so it always goes to `review`.
- Acceptance produces one new container row through the existing container-create REST route (no new business rule; only a new voice-side proposal type).

### 4.3 Edit: rename, append, edit content, change deadline (new)

VCP-v3 has zero edit-existing-item intents; only create. Needed for keyboard-free parity.

- New intents: `rename_item`, `append_to_item`, `edit_deadline`, `edit_content` (full replace — used sparingly, see below).
- `target_phrase` resolves to exactly one existing item through the same destination-resolver tiers as §8.4 (exact path → unique leaf → fuzzy-review → ambiguous). **Never resolves to a bulk set** — bulk is a separate intent (§4.5) so "edit" and "bulk edit" can't be confused by a policy bug.
- The proposal is a **diff**: old value vs new value, shown verbatim (never summarized/rewritten — matches VCP-v3's "body is never rewritten" rule in §8.1). Full-content replace (`edit_content`) is high-risk for silent data loss by mishearing, so it defaults to `review` always, is capped to items below a size threshold (say the existing content is short — e.g., a task title/short note), and larger note bodies over that threshold route the user to append-only or the manual editor instead of a full-body voice replace. Append is intrinsically safer (adds without touching existing text) and is the recommended default utterance shape: "add to the note called X: ...".
- `edit_deadline` reuses VCP-v3's whole §8.3 date parser unchanged — this is exactly the deadline-setting logic already built for task creation, applied to an existing task's `due_*` fields via `expected_version`.
- Accept path: existing `append_to_item`/`update_item` REST routes (already used by the MCP tools, per the MCP tool reference — `append_to_item`, `update_item` exist today), invoked by the accept endpoint the same way `/interpretations` is invoked today, with `expected_version` re-validated at commit.

### 4.4 Move, relationships, complete/reopen, archive/restore (VCP-v3 Phase 4, generalized)

VCP-v3 already designed `move_item`, `complete_task`, `reopen_task`, `archive_item` as review-only Phase 4 intents with "exactly one active target + version." I keep that design and extend it:

- Add `restore_item` (archive's inverse — VCP-v3 lists archive but not restore; restore is equally needed for keyboard-free coverage since a user can't otherwise reach the Archive page's restore button) and `link_items`/`unlink_items` (about/related_to — VCP-v3 explicitly calls "relation edits by voice" out of scope; I bring them in since "cover every meaningful UI action" includes relationships).
- `link_items`/`unlink_items` resolve **two** target phrases (source and target item) through the same resolver; ambiguity on either side forces `ambiguous` → voice disambiguation (§6.4).
- Disposition stays **review-only** for all of these at launch, same as VCP-v3 designed for move/complete/reopen/archive — I do not propose auto-apply for any state-changing or relationship intent in the initial rollout; that stays a possible later gate exactly as VCP-v3 reserves auto-apply for one narrow `create_task` case only.
- **Same-turn voice confirmation without a screen** (§6.2): for the single-target, no-destination-ambiguity case (e.g., "mark 'submit the report' as done"), the review readback + a one-word spoken "yes" is enough — this is the keyboard-free equivalent of VCP-v3's Accept button, not a new confirmation mechanism.

### 4.5 Bulk actions (new)

VCP-v3 explicitly excludes bulk operations ("unsupported"). Required for keyboard-free coverage of things like "archive everything I finished this week" or "complete all the tasks in the Kitchen renovation project."

- New intent `bulk_action` with `operation ∈ {archive, restore, complete, reopen}` (bulk create/delete are out — see below), a `scope` built from existing filters only (container, category, date range, state — the same filter vocabulary `GET /items`/`GET /tasks` already accept), never a free-text query (no "everything about the kitchen" — that's a search result set, not a bulk-safe scope).
- The backend resolves `scope` to a **concrete, bounded list of item IDs + their current versions at proposal time** — the proposal literally enumerates every affected item (id, title, current state) up to a cap (recommend 25; above that, `review` requires narrowing the scope, never silently truncates).
- Accept is **one atomic batch transaction** (extending the existing whole-batch-atomic `/interpretations` pattern already used for 1–10 create ops) — either all listed items transition or none do, each re-validated against its `expected_version` at commit (so an item changed since the proposal was built causes the whole batch to fail closed with a list of which ones changed, not a partial bulk write).
- **Bulk permanent delete and bulk create are explicitly out of scope** for voice in this plan — bulk delete combines two high-risk classes (irreversible + many-item blast radius) and is exactly the kind of operation this plan is more conservative about than the raw task ask; see the disagreement note in §4.6.
- Undo: one batch undo token that reverses every item in the batch (new capability — VCP-v3's undo is per-action; bulk needs a per-batch undo, described in §5.3).

### 4.6 Permanent deletion (narrow, deliberately harder than everything else)

The task asks for permanent deletion to be voice-reachable. VCP-v3's position ("excluded everywhere") is the safer default and I do not simply overturn it — I add a narrow path instead of removing the restriction:

- New intent `delete_permanently`, valid **only** on items already in Archive (matches the existing archive-first REST invariant — permanent delete already requires `archived` + `confirm=true` server-side, unchanged).
- Disposition is **always `review`**, never auto-apply, regardless of any future gate — this is the one place I hard-code a permanent exception rather than leaving it to the gate mechanism, because "prove it from evidence" (VCP-v3 §7.4's auto-apply justification) cannot certify irrecoverable operations from a speech transcript alone.
- **Exact confirmation phrase, not "yes."** The review readback states the item's title and container, then asks the user to repeat a short **randomly-chosen confirmation phrase** back exactly (e.g., "Say: delete forever, submit the report" — title interpolated, so a generic "yes" or a misheard adjacent word can't trigger it). The backend compares the *new* recording's transcript against the expected phrase (normalized) before calling the existing `confirm=true` delete route. A mismatch or low-confidence transcript re-prompts once, then falls back to requiring the on-screen confirm click.
- **My explicit disagreement/flag for the user:** I recommend that even with this phrase-confirmation, permanent deletion should ship **last**, after every other class has real-world data on transcription error rates from the same corpus VCP-v3 built (§15's gates), and that the fallback-to-screen-click option above should be the *permanent* default for this one operation rather than a temporary Phase-0 crutch — i.e., "keyboard-free" is a reasonable goal for every other class, but permanent, unrecoverable deletion is the one place I would keep a physical-input floor unless the accuracy data is very strong. Flagging this rather than silently deviating from the "no requirement to type" constraint.

### 4.7 Multi-intent and dependent commands (new — VCP-v3 caps at "≤3 create-only, atomic")

The task requires "creating a project plus several notes" as a first-class scenario. This needs an **operation-plan** abstraction, not just a bigger create batch.

- The processor still emits **only slots**, but for a multi-step utterance it emits an **ordered list of slot-sets**, each tagged with its own intent and an optional `depends_on_step` back-reference for cases where step 2 needs step 1's freshly created container (e.g., "create a project called Kitchen renovation, then add three notes to it: measurements, vendor comparison, and timeline").
- The **backend** (not the model) resolves dependencies: a step whose destination phrase is empty but whose plan position is textually "after" a `create_container` step is grounded to *that step's not-yet-existing container* symbolically (`$step[0].container_id`), resolved to a real ID only inside the single accept transaction, in step order.
- The proposal shown to the user is the **whole plan**: every step's operation type, target/new-container name, and content, in order, with a single "Accept all" (voice or screen) — no partial acceptance and no reordering; a per-step edit reruns extraction for that step only and re-renders the whole plan (small-batch enough that this stays cheap).
- Cap: recommend the existing "≤3 create-only, atomic" cap from VCP-v3 is too narrow for the stated example (a project + several notes is easily 4–6 steps); I'd raise it to a measured cap (propose starting at **≤10 steps**, create-only + at most one `create_container` step, gated by the same corpus-driven accuracy measurement as everything else) rather than picking a number a priori.
- Mixed step types (a plan containing both creates and an edit/complete/delete) are **not supported at launch** — always `ambiguous`/force a single-intent utterance — because dependency resolution + mixed operation semantics + irreversible-step confirmation compounds three hard problems at once; revisit only after single-type multi-step plans are proven (P3 gate).

## 5. Operation-plan schema and transaction semantics

This generalizes VCP-v3's single-item `CommandProposal` (§7.3) into a **plan** container that can hold 1..N steps, each of which is exactly VCP-v3's existing per-item shape.

```json
{
  "kind": "voice_command_plan",
  "schema_version": 1,
  "generation": 3,
  "inputs_sha256": "…",
  "policy_version": 1,
  "policy_evaluated_at": "2026-09-27T09:00:00+05:30",
  "steps": [
    {
      "step_index": 0,
      "intent": "create_container",
      "operation": { "type": "create", "item_type": "project", "name": "Kitchen renovation" },
      "resolution": { "duplicate_check": { "status": "none", "candidates": [] } },
      "warnings": [],
      "disposition": "review"
    },
    {
      "step_index": 1,
      "intent": "create_note",
      "depends_on_step": 0,
      "operation": {
        "type": "create", "item_type": "note",
        "title": "Measurements", "content_md": "",
        "destination": { "ref": "$step0.container_id" }
      },
      "resolution": { "destination": { "status": "pending_dependency", "source": "step_output" } },
      "warnings": [],
      "disposition": "review"
    }
  ],
  "plan_disposition": "review",
  "irreversible_steps": [],
  "explanation": "Create a new project and 3 notes inside it.",
  "confirmation_phrase": null
}
```

**Transaction semantics:**
- **One backend transaction accepts the whole plan** or none of it — extends the existing whole-batch-atomic `/interpretations` pattern (already atomic for 1–10 ops today) to be **plan-atomic**: dependent-step IDs are resolved in `step_index` order *inside* the same transaction, so a later step's `destination.ref` only becomes a concrete UUID at commit time, never before.
- `expected_version`/`expected_generation` apply to the **capture** as today; each step that targets an *existing* item additionally carries that item's `expected_version`, captured at proposal time and re-validated at commit (same stale-write protection as every other mutation in this codebase).
- If any step's target was mutated since the proposal (someone edited "Kitchen renovation" via the UI in between), the whole plan fails closed with a 409 that names the stale step — **no partial plan execution**, matching VCP-v3's existing "no silent partial writes" invariant (T23).
- `irreversible_steps` lists which step indices require exact-phrase confirmation (§4.6); a plan containing an irreversible step can never carry a `create_container`/dependent step in the same plan (mixing bulk/delete with multi-step creation is disallowed by policy, not just by convention, to keep the confirmation UX legible).
- `plan_disposition` is computed as the **most restrictive** of its steps' individual dispositions (`reject` > `review` > `auto_apply_eligible`) — a plan is never more permissive than its riskiest step.
- Undo: acceptance writes one **`voice_plan_id`** shared across all created/mutated items' provenance rows; a single "undo that" archives/reverts every item tagged with that plan ID in one action (new: this is the batch-undo mechanism referenced in §4.5 too — bulk actions and multi-step plans share the same undo-token design).

## 6. Disposition, confirmation, and disambiguation for the expanded action set

### 6.1 Extended disposition table (builds on VCP-v3 §12)

| Situation | Disposition |
|---|---|
| `query` (read-only) | executes immediately, no proposal |
| `create_note`/`create_task` (VCP-v3 rules unchanged) | per VCP-v3 §12 |
| `create_container` | always `review` |
| `rename_item`/`append_to_item`/`edit_deadline` | always `review` (still shown as a diff even on the fast voice-confirm path) |
| `edit_content` (full replace) | always `review`, and only offered below the size threshold (§4.3) |
| `move_item`/`link_items`/`unlink_items`/`complete_task`/`reopen_task`/`archive_item`/`restore_item` | always `review` at launch (matches VCP-v3's own Phase 4 stance) |
| `bulk_action` | always `review`; batch list shown/read in full before accept |
| `delete_permanently` | always `review` **and** exact-phrase confirmation; never auto-apply, ever (§4.6) |
| multi-step plan | `plan_disposition` = most restrictive step (§5) |
| any ambiguous target/destination on any of the above | `ambiguous` → voice disambiguation turn (§6.4) before any proposal is finalized |

No new intent in this plan is ever `auto_apply_eligible`; VCP-v3's single narrow auto-apply class (`create_task`, no destination, warning-free deadline) is the only one, unchanged, and stays gated behind its own §15 measurement.

### 6.2 Voice-only accept/reject/correct/undo (new — makes VCP-v3's screen-first review card keyboard-free)

VCP-v3's review card assumes a mouse (Accept/Edit/Discard buttons, keyboard Enter/E/Esc). For voice-only operation:

- After a proposal is computed, the system **reads back** a short, deterministic summary (backend-generated from the same fields the card renders — title, destination, deadline, warnings — never model-generated prose, so the readback can't drift from what will actually be written).
- Recognized follow-up utterances, scoped to *only the active proposal* (a short-lived server-side "awaiting confirmation for capture X" state, timeboxed — recommend 30 s, matching VCP-v3's UI polling cadence order of magnitude): **"yes"/"accept"/"do it"** → accept; **"no"/"cancel"/"discard"** → archive; **"undo"** (with no open proposal) → generic undo of the last accepted action *from this recording session*, never a session-unbounded "undo my last thing" that could reach an old, unrelated action; **"change the date to..."/"put it in ... instead"** → a targeted correction that re-runs only the affected slot through the backend policy package (not a full re-transcription), re-renders the readback, and asks again.
- **Every one of these is still a normal REST call** (`/proposal/accept`, `/captures/{id}/archive`, `/actions/{id}/undo`, `/proposal` again for a correction) — voice is a new *client* for existing endpoints, not a new trust boundary. The native shortcut helper (§7) or the browser tab sends the same authenticated requests the mouse-driven UI already sends.
- The on-screen review card remains available and is not replaced — voice confirmation is an additional channel to the same proposal, so a user who wants to look and click still can.

### 6.3 Exact confirmation for irreversible actions (new)

Generalizes §4.6 beyond delete: any step marked `irreversible` in the plan (currently: `delete_permanently` only, but the mechanism is generic so a future irreversible class doesn't need new plumbing) requires:
1. A deterministic, backend-generated confirmation phrase naming the specific target (never a generic "yes").
2. A **fresh recording** of the user speaking that phrase (not reuse of the original command's transcript — this defends against a single ambiguous utterance being replayed as its own confirmation).
3. Backend string comparison (normalized: casefold, punctuation-stripped) between the new transcript and the expected phrase — **not** a model judgment call on whether they "match well enough."
4. One retry on mismatch, then mandatory fallback to the on-screen confirm click (§4.6) — never a third voice attempt, to bound how many chances a misrecognition gets before failing safe to the slower, more certain path.

### 6.4 Voice disambiguation turn (new)

VCP-v3's `ambiguous` outcome today means "show a selector, stop." For keyboard-free use:

- The backend readback lists candidates **with a short index and a distinguishing breadcrumb** (container path, or last-edited date if titles collide): "I found two notes called 'Vendor comparison' — one in Kitchen renovation, one in Bathroom remodel. Which one?"
- A short follow-up ("the first one" / "the kitchen one" / "the second") is matched deterministically against the **exact list already presented** (index words, or a substring of the breadcrumb shown) — the backend does the matching, not the model; the model's job is again just to extract "which selection phrase did the user say," and the backend maps it against the finite candidate set it itself generated. This mirrors VCP-v3's trust boundary exactly: the model never gets to assert an ID, only a phrase, and the backend resolves the phrase against ground truth it already computed.
- If the follow-up still doesn't resolve to exactly one candidate (after one retry), the capture stays `awaiting_review` in Inbox for on-screen resolution — same fail-safe fallback pattern as §6.3.

## 7. System-wide macOS recording shortcut (new component — VCP-v3 has none)

VCP-v3 correctly notes a browser tab cannot register a global hotkey or record while unfocused. A keyboard-free primary interface needs a small native helper.

### 7.1 Architecture

- A lightweight **native macOS menu-bar helper app** (Swift/SwiftUI, or a minimal Rust/Tauri shell if the team prefers a non-Swift toolchain — recommend native Swift for the smallest footprint and the most reliable global-hotkey/Accessibility API support), running as a background agent (`LSUIElement`), started at login (optional, user-controlled).
- It talks to the **same local backend REST API** the browser proxy talks to (loopback, bearer token stored in macOS Keychain, not `.env`/plaintext) — it is a new client, not a new trust boundary or a new backend. It performs exactly the same two calls the browser does: `POST /voice-captures` (audio ingest) and polls `GET /captures/{id}` for the resulting proposal, then can either open the web UI's review card (`open` a deep link to `/captures/{id}`) or handle the voice-only accept/reject/correct loop from §6.2 itself via local TTS + a follow-up recording.
- Global hotkey registration via the Carbon `RegisterEventHotKey` API or a modern equivalent (`NSEvent.addGlobalMonitorForEvents` requires Accessibility/Input-Monitoring permission — expected and disclosed during setup, same category of permission Traceback's own recording already needs at the browser layer).

### 7.2 Two modes, both configurable

- **Push-to-talk**: hold the configured key combo → record; release → stop and submit. Matches the "hold to talk" mental model, minimizes accidental long recordings, and needs no separate "am I recording" ambiguity (the key is physically held).
- **Toggle / accessibility mode**: press once → start recording (with the existing 60 s auto-stop and a persistent, unmissable menu-bar + on-screen indicator per VCP-v3's accidental-activation mitigations); press again (or say "stop"/"done") → stop and submit. This mode exists specifically for **accessibility** — users who cannot comfortably hold a key combo for the duration of a longer dictation (the task explicitly asks for this as a named mode, not just a convenience toggle).
- Both modes are **user-remappable** (a settings pane in the helper app, stored locally, not synced anywhere) and **off by default** until explicitly configured, matching VCP-v3's "review-first, opt-in" posture for the rest of the feature.
- The helper enforces the **same single-recording mutex** as the browser's `VoiceCommandProvider` (§6, VCP-v3) via the loopback API itself (the backend, not each client, should own "is a recording already active" — recommend adding a lightweight backend-held recording-session lock, since today the mutex is purely client-side per VCP-v3 and a second *native* client wouldn't otherwise know about a browser tab's in-flight recording, and vice versa). This is a **new backend requirement** this plan adds on top of VCP-v3: a `POST /voice-session/start` / `/stop` pair (or reuse of the existing idempotency-key + duplicate-guard mechanism) so "only one recording at a time system-wide" holds across the browser and the native helper, not just within one process.

### 7.3 Feedback loop without a browser window focused

- Visible: a menu-bar icon state change (idle/recording/processing/awaiting-review/error) — cheap, always-there, matches VCP-v3's "visible indicator always" rule.
- Audible: a local TTS readback (§3) for the proposal summary and disambiguation prompts, so a user who triggered the shortcut from another app never needs to alt-tab to the browser to complete a command. The browser UI remains the full-fidelity review surface for anyone who does want to look.
- macOS native notifications (`UNUserNotificationCenter`) as a fallback/complement to TTS for a quick glance ("Task created: submit the report, due Fri 5 PM — tap to undo").

### 7.4 Lifecycle and failure modes (extends VCP-v3 §10 to the native client)

- Helper crash or backend unreachable mid-recording: same failed_unsent pattern as the browser (retain the blob locally, offer retry), just implemented in the native app instead of `VoiceCommandProvider`.
- API not running (per `local-development.md`'s manual start/stop model): helper shows "Traceback API not running" in the menu bar rather than silently failing; it does not attempt to start the API itself (out of scope — starting/stopping local services is an existing manual operational step, not something a voice-shortcut helper should take over silently).
- Permission not granted (mic or Accessibility/Input Monitoring): helper explains exactly which macOS System Settings pane to open; no silent no-op.
- Config file (hotkey bindings, mode) lives in the same local, non-synced location as other Traceback local config — no new cloud/sync surface.

## 8. Required changes by layer

**Backend** (extends `backend/voice.py`, `backend/voice_service.py`, `backend/voice_policy/`):
- New intents in the processor slot schema and the backend policy package: `query`, `create_container`, `rename_item`, `append_to_item`, `edit_deadline`, `edit_content`, `link_items`, `unlink_items`, `restore_item`, `bulk_action`, `delete_permanently`; extends the existing closed enum, never opens it to free text.
- Extend `CommandProposal` → `voice_command_plan` (§5): ordered steps, `depends_on_step`, `irreversible_steps`, `confirmation_phrase`, `plan_disposition`, shared `voice_plan_id` for batch undo.
- New destination/target resolver reuse for two-sided relation edits (source + target).
- New system-wide recording-session lock (`voice-session/start|stop` or equivalent), so the mutex is backend-held, not client-held, once a second client (the native helper) exists.
- New batch-undo mechanism keyed by `voice_plan_id`, extending the existing per-action undo.
- New exact-phrase confirmation flow for `irreversible_steps` (generate phrase, verify against a fresh transcript, one retry, then fail closed to the screen).
- `GET /capabilities` gains fields for the new intents' individual enable flags (each new class independently toggle-able, same as VCP-v3's existing `voice_commands_enabled`/`voice_auto_apply_intents` pattern) so bulk/delete/multi-step can each be rolled out and rolled back independently.

**Frontend**:
- `CommandReviewCard` generalized to render a **plan** (list of steps) instead of always exactly one op; a diff view for edits; a full enumerated list view for bulk actions (never collapsed/summarized — "affected 14 items" must be individually inspectable, matching VCP-v3's "no confidence badge, show the real thing" ethos).
- Voice-native confirmation loop UI state (listening-for-confirmation, listening-for-disambiguation) surfaced in the tray even when the review card isn't open, for parity with the native helper's TTS-only path.
- A deep-link route (`/captures/{id}`) already exists per VCP-v3 — extend it to render a plan.

**Processor**:
- `processor/voice.py`: extend the strict output schema to accept ordered multi-step slot arrays (still `extra="forbid"`, still no IDs/dates/verdicts from the model — same trust boundary, more slots).
- TTS invocation for read-only queries and readback (or delegate TTS entirely to the native helper/browser rather than the processor, to keep the processor's job "STT + slot extraction only" — recommend TTS lives in the **client** (browser or native helper), not the processor, to avoid growing the processor's responsibility beyond VCP-v3's "processor has no DB access, no policy" boundary).

**Native macOS component** (new, §7): menu-bar helper, global hotkey registration, push-to-talk/toggle modes, Keychain-stored token, local TTS/notifications, its own settings pane.

**Migrations**: expected none for JSONB-shaped plan/proposal fields (same reasoning as VCP-v3 §9.7); a new `voice_plan_id` column (or JSONB field) on the provenance/action tables for batch-undo grouping is the one plausible schema change, and even that could start as JSONB metadata before being promoted to an indexed column if measurement shows batch-undo lookups need it.

## 9. Phased plan (P0–P4)

**P0 — Read-only voice + measurement (no new write surface)**
- Ship `query` intent end-to-end: search, read note/task aloud, list inbox/tasks, navigate. No proposals, no confirmation, immediate execution over existing read endpoints.
- Stand up local TTS (native OS synthesizer first) and prove offline/no-cloud.
- Build the native macOS helper's **push-to-talk only** (defer toggle mode to P1) wired to the *existing* VCP-v3 create-note/create-task flow, so the shortcut ships before any new intent is designed, proving the hardest new infra (global hotkey, Keychain token, backend-held recording lock) against a write path already gated by VCP-v3.
- Acceptance: read-only corpus (analogous to VCP-v3 §15's corpus but for queries) hits ≥90% correct-answer rate measured against a labeled set; native helper push-to-talk records/uploads/creates via the existing pipeline with the new backend-held lock preventing double-recording across browser+helper; TTS readback intelligible in a blind test; zero writes from any `query` utterance (verified by a policy-package unit test asserting `query` never reaches the accept path).

**P1 — Edit, relate, restore + toggle/accessibility shortcut mode**
- `rename_item`, `append_to_item`, `edit_deadline`, `edit_content` (below threshold), `link_items`/`unlink_items`, `restore_item`.
- Voice-only accept/reject/correct/undo loop (§6.2) and the voice disambiguation turn (§6.4), so these new intents are actually usable keyboard-free, not just reachable-then-stuck-on-a-screen.
- Native helper: toggle/accessibility mode, remappable bindings, menu-bar state indicator, notification fallback.
- Acceptance: each new intent's own accuracy gate (reuse VCP-v3 §15's methodology — ≥90% intent accuracy, 0 false-positive writes by construction, grounding-correct spans ≥90%) measured on an extended corpus that adds these intents' utterance patterns; voice confirm/reject/undo proven against the existing corpus's create flows first (lowest-risk regression surface) before being trusted for edits; a week of review-first daily use with logged outcomes, same bar VCP-v3 set for its own Phase 3.

**P2 — Containers, bulk actions, multi-step plans**
- `create_container` (duplicate-name policy), `bulk_action` (scoped, enumerated, atomic batch, capped list size), the `voice_command_plan` schema and dependent-step resolution (§5), batch undo via `voice_plan_id`.
- Acceptance: bulk-action corpus proving 0 partial-batch writes under injected mid-batch version conflicts (a scoped item is edited by another client mid-proposal → whole batch fails closed, verified by test); multi-step plan corpus (the task's own "project + several notes" example as a named regression case, plus at least 10 variants) proving dependency resolution never produces a wrong container reference; batch undo reverses 100% of a plan's items in one action in test.

**P3 — Permanent deletion (narrow, phrase-gated) and mixed hardening**
- `delete_permanently` intent with exact-phrase confirmation (§4.6), archived-only precondition, always-review, no auto-apply ever.
- Re-run VCP-v3's full §15 gate table plus this plan's read-only/edit/bulk/plan corpora together, looking specifically for cross-intent confusion (e.g., "delete" misclassified as `archive_item` or vice versa) now that the enum is much larger than VCP-v3's original five intents.
- Acceptance: 0 unconfirmed permanent deletions in ≥300 trials that include intentionally ambiguous/adjacent phrasing ("get rid of," "remove," "delete" said near an archive-only context); phrase-confirmation mismatch correctly falls back to the on-screen click every time it's tested; full network-off, thermal, and native-helper-crash drills (extending VCP-v3 §16's real-device test list to the new helper process).

**P4 — Optional expansion (auto-apply widening, alternate wake modes) — explicitly not committed**
- Only after P0–P3 have real accuracy data: consider widening VCP-v3's single auto-apply class, or a narrow always-listening "Hey Traceback"-style mode as an *alternative* to the hotkey (still local, still opt-in) — flagged as future, not designed here, mirroring VCP-v3's own treatment of speculative later phases. Any widening of auto-apply to intents beyond VCP-v3's original `create_task` case, or any reconsideration of the permanent-delete confirmation floor in §4.6, should require the same kind of explicit, separately-reviewed decision VCP-v3 demands for its own out-of-scope items — not a default outcome of "P4 shipped."

## 10. Risks (beyond VCP-v3's existing T1–T36)

- **Enum growth erodes the trust boundary's simplicity.** VCP-v3's safety story leans on a small closed intent set the backend can reason about exhaustively; going from 5 intents to ~16 multiplies the policy-package surface and its test matrix. Mitigation: every new intent gets its own row in the disposition table (§6.1) and its own gate gate before shipping, not a blanket "voice v2 is done" milestone.
- **Cross-intent confusion at the boundary** (edit vs bulk-edit, archive vs delete, complete vs reopen said with double-negatives). Mitigation: the P3 hardening pass explicitly tests adjacent/confusable phrasing, not just each intent's own happy path.
- **Native helper as a second, less-reviewed client of the same backend.** It bypasses the browser's `VoiceCommandProvider` state machine entirely. Mitigation: backend-held recording lock (§7.2) and identical REST usage rather than a shortcut-specific API surface.
- **TTS adds a second local-model-adjacent dependency** (even if OS-native) to reason about for the "fully local" guarantee. Mitigation: prefer the OS synthesizer (already on-device, no model download) over a bundled neural TTS model unless quality demands it.
- **Multi-step plans are the single largest new complexity budget item.** Mitigation: cap step count and step-type homogeneity (§4.7) rather than trying to support arbitrary composition on day one.
- **Permanent deletion by voice is the one class where "keyboard-free" and "safe" pull against each other hardest.** Explicitly flagged in §4.6 rather than resolved by aggressive engineering.

## 11. What I did not change

VCP-v3's Phase 0–3 measurement methodology, its date/timezone parser, its destination resolver, its idempotent ingest protocol, its capture state machine and version/generation/lease mechanics, its storage/archive-first lifecycle, and its rollout/rollback story are all reused as-is. This plan is additive on top of an already-implemented, tested slice (379 backend tests, 98 frontend tests per `docs/current-status.md`); nothing here proposes weakening any of VCP-v3's existing guarantees.
