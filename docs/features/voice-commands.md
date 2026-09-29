# Voice commands (implemented, review-first)

Status: implemented 2026-09-26 as the first usable slice of the [voice command capabilities plan](voice-command-capabilities-plan.md), which remains the reviewed source of truth for intent and rules. **Off by default. Nothing is applied automatically. Speech-recognition and command-understanding quality on real voice are not benchmarked** (see [what remains manual](#what-remains-manual-phase-0-validation)).

## What you can do

Use the global voice panel to record one short command, or choose **Type instead** to enter it. The panel follows you across Inbox, Tasks, notes, categories, projects, and folders:

- “Add a note called Normal forms in Learning / Database Systems.”
- “Add Vendor comparison in project Kitchen renovation.”
- “Remind me to submit the report next Friday at 5 PM.” (creates a **task with a deadline**; there are no reminders or notifications)

The audio is saved first. A local processor transcribes it, and Qwen suggests spoken-form slots. The backend then computes the proposal and shows a review card. You Accept, edit then Accept, save it as a note or task by hand, keep it in Inbox, or discard (archive) it. Undo after Accept archives the created item.

## Turning it on and off

Voice is controlled only by backend environment (or `.env`), read at API start-up. Restart the API after changing it.

| Variable | Default | Meaning |
|---|---|---|
| `TRACEBACK_VOICE_COMMANDS_ENABLED` | `false` | Master switch. Off: the global voice panel is hidden; manual note and task forms remain available. |
| `TRACEBACK_VOICE_MAX_SECONDS` | `60` | Recording auto-stops; longer audio is refused. |
| `TRACEBACK_VOICE_MAX_UPLOAD_BYTES` | `10485760` | Backend cap. The Next proxy has its own `TRACEBACK_VOICE_MAX_UPLOAD_BYTES` (server-side only; keep it ≥ this). |
| `TRACEBACK_VOICE_MIN_FREE_DISK_BYTES` | `2147483648` | Ingest returns 507 before writing below this; the mic warns at 2× via `low_disk`. |
| `TRACEBACK_VOICE_ACCEPTED_MIME_TYPES` | see `backend/config.py` | Detected (`file --mime-type`) types accepted; WebM/Opus is labelled `video/webm`. |
| `TRACEBACK_VOICE_DUPLICATE_WINDOW_S` / `TRACEBACK_VOICE_QUEUE_AGING_S` | `120` / `300` | Duplicate-recording guard; queue aging. |
| `TRACEBACK_VOICE_AUTO_APPLY_INTENTS` | *(empty)* | **Must stay empty.** Auto-apply is not implemented in this release; any value makes the API refuse to start. |

Rollback: set `TRACEBACK_VOICE_COMMANDS_ENABLED=false`, restart the API. New voice captures are refused (403); `claim-next` and per-capture claim skip/refuse voice captures; transcript correction and retry return 409 `capability_disabled`. Stranded `pending`/`failed` voice captures stay in Inbox with their audio; finish them with **Type it instead** (manual interpretation, no worker needed). Existing proposals stay manually acceptable, and discard always works. The UI never falls back to the retired auto-interpreting microphone path.

The UI learns the state from `GET /api/v1/capabilities` (no-store; fetched on load and on every mic click). There is no `NEXT_PUBLIC_*` flag.

## Trust boundary

- Qwen output is a strict schema of **spoken-form slots only** (intent, title, content, destination/date/time *phrases*, flags). It has no field for an ID, ISO date, weekday, offset, timezone, or verdict; extra keys fail validation in the processor and are rejected (422) by the backend.
- The processor holds no policy. It sends `slots`, `model_confidence` (stored for offline evaluation, never rendered or used in decisions), and STT metadata.
- The backend recomputes everything from stored evidence with one pure package, `backend/voice_policy/` (no I/O; the same code the tests run): grounding of every span in the transcript, intent lexicon, deterministic date/time parsing, destination resolution over the live catalog, warnings, and disposition. Model flags can only add review.
- Dates use `captured_at` (when you spoke) in your `source_timezone` as the anchor, never receipt time. Skew (`delayed_ingest`, `clock_ahead`) forces review, shows both times, and offers the receipt-anchored date as an alternative without replacing the anchor.
- Every proposal is `review` (or `reject` for unsupported/restricted). `auto_apply_eligible` can only be produced by the pure policy when a caller passes an enabled intent list, which the backend never does.
- A past deadline is allowed only with explicit confirmation (`422 overdue_confirmation_required`, resend with `confirm_overdue: true`); manual forms and manual interpretation keep their existing no-such-rule behavior.
- `capture_only`, `ambiguous`, and `unsupported`/restricted outcomes stay `awaiting_review` in Inbox until you act; a capture never becomes `resolved` without an item.
- Organization intents (move, complete, reopen, archive), deletion, and folder/project creation by voice are recognised only to refuse them (`unsupported`, nothing written).

## REST surface

| Route | Who | Notes |
|---|---|---|
| `GET /capabilities` | UI, MCP | Enabled state, limits, accepted types, `low_disk`, queue stats. `Cache-Control: no-store`. |
| `POST /voice-captures?size&sha256&captured_at&source_timezone&entry_point&…` | UI | Raw audio body. **Requires** `Idempotency-Key`. One transaction saves bytes, asset, capture, revision. Same key + payload replays; different payload 409; declared size/digest/type verified (413/422/415); low disk 507; duplicate recording within 2 minutes 409 with the existing `capture_id`. |
| `POST /captures` with `processing_profile: "voice_command"` | UI “Type instead”, MCP | Typed only; `captured_at` and `source_timezone` required. 403 while disabled. |
| `POST /captures/claim-next` | processor | Aged-first, then voice-preferred with at most two consecutive voice claims while older non-voice work waits; skips voice while disabled; locks only the claimed row; 204 when idle; no version bump. |
| `POST /captures/{id}/transcript` | processor | Checkpoint after STT, before Qwen. Lease+generation fenced; **no version bump, no revision**; `no_speech` fails the capture. `/fail` keeps a checkpointed voice transcript. |
| `POST /captures/{id}/proposal` | processor | Voice body `{expected_version, expected_generation, lease_token, slots, model_confidence?, stt?}`; the backend stores the computed `CommandProposal`. |
| `POST /captures/{id}/proposal/accept` | UI, MCP | `{expected_version, expected_generation, overrides?, confirm_overdue?}`; exactly one item via the shared interpretation transaction; server-computed override audit in the capture revision. |
| `POST /captures/{id}/corrections` with `transcript_text` (or `captured_at`/`source_timezone`) | UI, MCP | Requeues at a new generation and clears the proposal (only while enabled). |
| `POST /captures/{id}/interpretations` | UI, MCP | Manual “Save as”/“Type it instead”; voice captures require exactly one note or task; processor mode is refused for voice (`auto_apply_unavailable`) and for legacy `general` audio (`legacy_audio_requires_review`). |

Accept uses the destination's **current** version (it must still exist, be active, and be the same type, else 409 `destination_changed`); an override may pin a version. 409 details always carry the current `version`, `generation`, `state`, and `proposal_sha256` so the card can refetch, keep your edits, and silently resubmit once only when nothing changed. No migration was needed (JSONB profile/proposal/audit fields).

## Audit evidence

The `interpreted` revision of a voice capture records `voice_audit`: `proposal_present`, `proposal_generation`, `proposal_sha256`, `policy_version`, `accept_path` (`accept_endpoint` or `manual_interpretation`), `accepted` (type, title, deadline, destination, `content_sha256`, `content_length`), server-diffed `edited_fields`, and `overdue_confirmed`. The `proposal`/`processing_failed` revisions record transcript hash/length and STT metadata; archiving an `awaiting_review` capture records `discarded_after_proposal`. The transcript-checkpoint evidence (timestamp, STT model, duration) lives on the `checkpoint_transcript` action row.

## Processor pipeline

`claim-next` → download → local `ffmpeg` normalization to 16 kHz mono WAV (fixed argv, timeout, 65 s cap) → clips under 0.7 s or blank output are `no_speech` and never reach Qwen → whisper.cpp → **transcript checkpoint** → Qwen slots → slot submission. Any failure leaves the capture `failed` with the audio (and transcript, if it exists) retained; Retry reruns only the missing stage. A corrected transcript skips Whisper. Legacy `general` audio is transcribed, checkpointed through `/fail`, and stopped with `legacy_audio_requires_review`. The scheduler polls every 3 s while voice is enabled, else 15 s.

## MCP

`create_capture(processing_profile="voice_command", source_type="typed", …)` (entry point `mcp_typed`, never auto-applied), `get_capture`/`list_captures`, `correct_capture` (incl. `transcript_text`), `retry_capture`, `accept_capture_proposal`, `apply_capture_interpretation`, `archive_capture`, and read-only `get_capabilities`. Audio ingest, `POST /assets` for audio, claim/claim-next/fail/transcript/processor-mode routes, and any voice deletion stay out of MCP.

## What was not built

Auto-apply (any intent), organization/mutation intents and multi-intent splitting, the asset reconciler script and `GET /storage/summary` with the guided reclaim view, thermal/low-power deferral, Ollama keep-alive tuning, the offline metrics/evaluation scripts, any recording keyboard shortcut, and the Tasks card's “Open full form” hand-off (the card's Save as / Type it instead panels are the manual path). `entry_point: "mcp_typed"` on a typed command is set by the MCP adapter; the backend cannot verify who called `POST /captures`, but it refuses `mcp_typed` on audio ingest. These are Phase 4–6 or hardening items in the plan.

## What remains manual (Phase 0 validation)

None of this could run unattended, and **none is claimed to have passed**:

1. Record with real Chromium and Safari microphones through the UI; note each browser's actual recorder MIME type, what `file --mime-type` labels it, that ffmpeg decodes it, and typical clip sizes. (Only synthetic ffmpeg clips were checked: WebM/Opus is `video/webm`, MP4/AAC is `video/mp4`, M4A is `audio/x-m4a`, Ogg/Opus is `audio/ogg`.)
2. Build the ≥150-utterance corpus outside Git (the three seed patterns and variants, dates, duplicate names, self-corrections, multi-intent, injection speech, accents, noise, ≥20 no-speech clips) and score real Whisper small and real `qwen3.5:4b` against the plan's §15 gates using the typed corpus through `backend/voice_policy/`. No scoring script exists yet.
3. Measure Stop → review card p95 (warm and cold), 20 consecutive commands (memory, swap, thermal), battery, and 3 s vs 15 s idle polling cost; decide Ollama keep-alive.
4. Verify a full network-off run.
5. Send a real 10 MB body through the running Next proxy and watch its memory.
6. Run the drills in the real app: `kill -9` the API mid-upload, fill a scratch volume (507), toggle the env and restart, disable voice with a `pending` capture and finish it via **Type it instead**, accidental-activation checks.
7. Take a verified backup before enabling voice on the daily-use install, then use it review-first for a week with logged outcomes.

One gated smoke test (`test_real_whisper_and_qwen_reach_a_review_proposal_for_a_synthetic_utterance`) runs real ffmpeg, whisper.cpp small and `qwen3.5:4b` over HTTP on macOS `say` speech and asserts only that the result reaches review with the transcript checkpointed and nothing created. An ad-hoc run of five synthetic utterances produced plausible proposals for four, and Whisper heard “Add” as “8” once (so it became a `capture_only` review). That is anecdote from synthetic speech, not a benchmark.

The rest of the tests use stubbed Whisper/Qwen and fake browser recorder APIs; they prove the contract, not recognition quality or real-device behavior.
