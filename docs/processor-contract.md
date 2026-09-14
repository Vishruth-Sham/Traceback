# Local processor integration contract (2026-09-14)

Status: implemented. The ownership notes below are historical coordination context. The current runner talks only to authenticated loopback REST. It also receives existing project/folder IDs and a capture `processing_profile`; `task_quick_add` requires exactly one task, enforced by both the interpreter and backend.

For `note_quick_add`, the runner reads the canonical `/locations` catalog and uses a separate strict schema containing only title, one allow-listed destination, explanation, and optional coarse confidence. It never returns note content and submits to `/captures/{id}/proposal` rather than `/interpretations`; PostgreSQL writes remain backend-owned.

Worker ownership: `processor/`, `scripts/model_*`, `tests/test_processor*`, and `docs/local-models.md`. Coordinator owns backend, capture migrations, integration, and dependency files. Coordinate proposed dependency additions; never edit another worker's files. No commits, cloud inference, microphone recording, or unrelated personal-file access.

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
