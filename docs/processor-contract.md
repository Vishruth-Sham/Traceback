# Local processor integration contract

Status: implemented; reviewed 2026-09-26. The current runner talks only to authenticated loopback REST. It receives existing project/folder IDs and a capture `processing_profile`; `task_quick_add` requires exactly one task, enforced by both the interpreter and backend. `note_quick_add` produces a reviewable placement proposal rather than directly creating an item.

For `note_quick_add`, the runner reads the canonical `/locations` catalog and uses a separate strict schema containing only title, one allow-listed destination, explanation, and optional coarse confidence. It never returns note content and submits to `/captures/{id}/proposal` rather than `/interpretations`; PostgreSQL writes remain backend-owned.

Historical coordination note: the implementation worker originally owned `processor/`, `scripts/model_*`, `tests/test_processor*`, and `docs/local-models.md`, while integration remained coordinator-owned. Those boundaries are not ongoing repository policy. The durable product constraints remain: no cloud inference fallback, no processor database writes, no model-directed arbitrary file access, and no microphone recording inside the processor adapter.

Implement synchronous Python adapters with no database writes:

- `transcribe(audio_path: Path) -> str` using whisper.cpp; audio is already persisted by backend, not an arbitrary path from model output.
- `interpret(text: str, context: dict) -> dict` using loopback Ollama qwen3.5:4b, bounded input/output and rounds. Return a validated proposal in the envelope below. Model may read supplied context, never execute SQL/shell or mutate data directly.
- A configurable adapter class/module is fine; document exact import and signatures. Keep setup/model download opt-in and weights outside Git. Runtime failures must raise useful exceptions so the caller marks the saved capture failed.

Proposal envelope:

```json
{"items": [{"item_type": "note", "title": "Example", "content_md": "Original meaning", "category_id": null, "project_id": null, "folder_id": null, "due_date": null, "due_time": null, "due_timezone": null}]}
```

Supported item types: note/task/project. General captures permit at most 10 proposed items; `task_quick_add` requires exactly one task. Task deadline rules match `backend/schemas.py`; no invented timestamps, completion, destructive operations, or planned date. Category/project/folder IDs must come from supplied context; uncertain destination is null (Inbox). Context includes `captured_at`, `source_timezone`, `source_date`, and `processing_profile` when known. If relative dates cannot be grounded, preserve them in content and leave deadline null. Original text/audio remains separate and immutable.

Backend integration will claim a saved capture generation with a lease, transcribe voice, call the proposal adapter, and submit one atomic interpretation. Backend validates generation/lease and item schemas, creates source links and revisions, and marks resolved in one transaction. Manual resolution invalidates stale leases/generations. Retry uses a new generation and explicit backend control. One active model job; no automatic cloud fallback.

Runtime acceptance: verify installed tools and actual model tag/digest, then run small synthetic/approved sample checks and measure latency and memory where feasible. Do not claim a full personal-recording quality benchmark without representative recordings. Report unavailable runtimes or model support accurately. Document expected installation/download disk use before initiating large downloads; user has authorized model setup for this work.

## Voice command pipeline (implemented 2026-09-26)

For `processing_profile: "voice_command"` the runner uses `POST /captures/claim-next` (backend-owned fairness), then: download the single audio asset → `ffmpeg` to 16 kHz mono WAV → whisper.cpp → `POST /captures/{id}/transcript` (durable **before** any interpretation) → Qwen → `POST /captures/{id}/proposal` with `{slots, model_confidence, stt}`. The Qwen schema is spoken-form slots only and is `extra="forbid"`; the processor makes no dates, IDs, destination matches, or dispositions and imports nothing from `backend/`. No speech (blank output, under 0.7 s) is checkpointed as `no_speech` and never reaches Qwen. Other failures call `/fail` with a specific `error_code` (`unsupported_audio`, `audio_too_long`, `TranscriptionError`, `InterpretationError`, …); the backend preserves a checkpointed transcript and a retry reuses it. A corrected transcript (`corrections.transcript_text`) skips Whisper. Typed voice commands use their immutable `raw_text` and skip STT.

Legacy `general` audio captures are still transcribed, but the transcript is kept via `/fail` with `legacy_audio_requires_review` and nothing is auto-interpreted; the backend also refuses processor-mode interpretation of them. Typed `general` and quick-add behavior is unchanged. `run_once` falls back to the old newest-pending query only when the backend has no `claim-next`. Configure ffmpeg with `TRACEBACK_PROCESSOR_FFMPEG_BINARY`, `..._FFMPEG_TIMEOUT_S`, `..._VOICE_MAX_AUDIO_SECONDS`, `..._VOICE_MIN_AUDIO_SECONDS`. The scheduler polls every `voice_poll_interval_s` (3 s) while `/capabilities` reports voice enabled, else `poll_interval_s` (15 s). Not implemented: thermal/low-power deferral.
