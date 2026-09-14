# Traceback

A voice-first personal agent for preserving thoughts and references and managing persistent memory alongside tasks, lists, and reminders through its own UI and MCP.

The local FastAPI REST API now implements manual notes, tasks, projects and nested folders, fixed categories, deadlines, single-parent filesystem containment, other relationships, Inbox placement, version conflicts, archive/restore, immutable captures, local attachments, source links, and durable processing state. A bounded REST-only processor can transcribe audio with local whisper.cpp and propose validated item writes with local Ollama `qwen3.5:4b`; typed captures skip transcription. Tasks also have a free-text quick add: the original text and client capture time are saved first, then the processor must produce exactly one structured task. A thin local stdio MCP adapter (`traceback_mcp`, official `mcp` SDK) exposes the same REST surface to Codex and Claude Code; it calls REST only, never the database directly. A desktop-only Next.js frontend (`frontend/`) implements navigation, Inbox classification, Tasks with deadline/completion filters, categories, Projects/folders, typed/audio capture, and archive/restore against the same canonical IDs; see [docs/local-development.md](docs/local-development.md#frontend-desktop-web-ui). The personal-memory graph and mobile are later milestones; Skills stays a static planned-capabilities page.

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

- [Initial implementation plan](docs/initial-plan.md)
- [Local backend plan: data model, storage, REST and MCP](docs/backend-plan.md)
- [Local MCP adapter: tool catalog, configuration, client setup](docs/mcp-adapter.md)
- [Desktop UI plan](docs/ui-plan.md)
- [Frontend design QA](design-qa.md)
- [Future personal memory and graph plan](docs/personal-memory-plan.md)
- [Updated v0 product and architecture handoff](docs/amnesiarch_v0_handoff_updated.md)
- [Original v0 product and architecture handoff](docs/amnesiarch_v0_handoff.md)
