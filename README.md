# Traceback

A local-first personal capture and organization application for preserving thoughts and references alongside notes, tasks, projects, and folders through its own UI and MCP.

The local FastAPI REST API implements manual notes, tasks, projects and nested folders, fixed categories, deadlines, single-parent containment, other relationships, Inbox placement, version conflicts, archive/restore, immutable captures, local attachments, source links, and durable processing state. A bounded REST-only processor supports local whisper.cpp transcription and validated Ollama `qwen3.5:4b` interpretation; typed captures skip transcription. Free-text task quick add creates one structured task, while note quick add presents a location proposal for review before saving. A local stdio MCP adapter exposes the same business rules to Codex and Claude Code without direct database access. The desktop Next.js frontend uses those canonical IDs and APIs. See [current status](docs/current-status.md) for the exact implemented/deferred boundary.

Opt-in, review-first voice commands (off by default; see [voice commands](docs/features/voice-commands.md)) save the audio first, transcribe and interpret it locally, and show a proposal you accept, edit, or discard. Nothing is applied automatically. Recognition and command-understanding quality on real voice has not been benchmarked, and the manual validation that remains is listed in that document.

Reminders, automatic Inbox aging, the personal-memory graph, hosted deployment, and mobile are not implemented. The Skills page is a static capability register, except that its Voice commands entry follows the server's capabilities.

## Run locally

Install Python 3.12–3.14, uv, and PostgreSQL 17 (`brew install postgresql@17`), then run from this directory:

```sh
uv sync --extra test --locked
python3 scripts/local_db.py init
.venv/bin/alembic upgrade head
.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

The setup generates private credentials in ignored `.env` and `.local/traceback/`, and starts a project-local PostgreSQL cluster on `127.0.0.1:55432`. It preserves existing configuration and data. The API requires `Authorization: Bearer <TRACEBACK_API_TOKEN>` from `.env`. Do not expose these local services remotely.

See [local startup, configuration, stop, backup and restore](docs/local-development.md) and [the implemented API contract](docs/backend-api.md). Run the PostgreSQL acceptance suite with `.venv/bin/pytest -q` after database setup; it creates and removes its own fresh database and does not reset the application database.

Start the desktop UI in a second terminal:

```sh
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`. The frontend's ignored `.env.local` must contain the same API token generated for the backend; see the local-development guide for the exact configuration.

The processor handles at most one pending capture per invocation; run it once with:

```sh
python3 scripts/model_setup.py
.venv/bin/python -m processor.runner
```

or keep it running unattended in the background with the local scheduler/lifecycle wrapper (no launchd/cron registration, nothing outside this checkout):

```sh
python3 scripts/processor_service.py start
python3 scripts/processor_service.py status
python3 scripts/processor_service.py stop
```

Use `python3 scripts/model_setup.py --install` only when the reported local dependencies are missing; it downloads model files outside this repository. See [local model setup, the scheduler, measured runtime evidence/benchmarks, and limitations](docs/local-models.md).

Run the local MCP stdio adapter, once the API above is running, with:

```sh
.venv/bin/python -m traceback_mcp
```

See [the MCP adapter: tool catalog, configuration, and Codex/Claude Code stdio setup](docs/mcp-adapter.md).

Automatic Inbox movement is disabled. No model is required for manual operations, and there is no cloud fallback. Both the backend and Ollama URLs are validated as plain-HTTP loopback addresses.

## Documentation

- [Current implementation status and next milestone](docs/current-status.md)
- [Initial implementation plan](docs/initial-plan.md)
- [Local backend plan: data model, storage, REST and MCP](docs/backend-plan.md)
- [Local MCP adapter: tool catalog, configuration, client setup](docs/mcp-adapter.md)
- [Desktop UI plan](docs/ui-plan.md)
- [Frontend design QA](design-qa.md)
- [Future personal memory and graph plan](docs/personal-memory-plan.md)
- [Historical updated v0 handoff (old Amnesiarch name)](docs/amnesiarch_v0_handoff_updated.md)
- [Historical original v0 handoff (old Amnesiarch name)](docs/amnesiarch_v0_handoff.md)
