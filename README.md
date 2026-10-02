# Traceback

A local-first personal capture and organization application for preserving thoughts and references alongside notes, tasks, projects, and folders through its own UI and MCP.

The local FastAPI REST API implements manual notes, tasks, projects and nested folders, fixed categories, deadlines, single-parent containment, other relationships, Inbox placement, version conflicts, archive/restore, immutable captures, local attachments, source links, and durable processing state. A bounded REST-only processor supports local whisper.cpp transcription and validated Ollama `qwen3.5:4b` interpretation; typed captures skip transcription. Free-text task quick add creates one structured task, while note quick add presents a location proposal for review before saving. A local stdio MCP adapter exposes the same business rules to Codex and Claude Code without direct database access. The desktop Next.js frontend uses those canonical IDs and APIs.

Opt-in, review-first voice commands (off by default) save the audio first, transcribe and interpret it locally, and show a proposal you accept, edit, or discard. Nothing is applied automatically. Recognition and command-understanding quality on real voice has not been benchmarked.

Reminders, automatic Inbox aging, the personal-memory graph, hosted deployment, and mobile are not implemented.

## Run locally

Install Python 3.12–3.14, uv, and PostgreSQL 17 (`brew install postgresql@17`), then run from this directory:

```sh
uv sync --extra test --locked
python3 scripts/local_db.py init
.venv/bin/alembic upgrade head
.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

The setup generates private credentials in ignored `.env` and `.local/traceback/`, and starts a project-local PostgreSQL cluster on `127.0.0.1:55432`. It preserves existing configuration and data. The API requires `Authorization: Bearer <TRACEBACK_API_TOKEN>` from `.env`. Do not expose these local services remotely.

Run the PostgreSQL acceptance suite with `.venv/bin/pytest -q` after database setup; it creates and removes its own fresh database and does not reset the application database.

Start the desktop UI in a second terminal:

```sh
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`. The frontend's ignored `.env.local` must contain the same API token generated for the backend; see the local-development guide for the exact configuration.

On macOS, after first-time setup, double-click `Traceback.app` in this folder to start the local stack in the background and open the UI. Quit the app to stop its services. If the app is absent in a new checkout, create it with `bash scripts/build_mac_launcher.sh`.

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

Use `python3 scripts/model_setup.py --install` only when the reported local dependencies are missing; it downloads model files outside this repository.

Run the local MCP stdio adapter, once the API above is running, with:

```sh
.venv/bin/python -m traceback_mcp
```

Automatic Inbox movement is disabled. No model is required for manual operations, and there is no cloud fallback. Both the backend and Ollama URLs are validated as plain-HTTP loopback addresses.

Private development notes are kept locally under ignored `docs/`.
