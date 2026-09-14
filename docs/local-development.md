# Local development on macOS

Traceback uses Python and PostgreSQL directly on the Mac. Manual REST/MCP/UI operations do not require Docker, Supabase, Whisper, or Ollama. Audio processing and AI-organized typed captures (including Tasks free-text quick add) require the optional local Whisper/Ollama processor. The PostgreSQL cluster belongs to this checkout and binds to `127.0.0.1:55432`; it is independent of Homebrew services.

## Prerequisites and first start

Install Python 3.12–3.14, uv, and PostgreSQL 17 binaries. On Apple Silicon, the default binary directory is `/opt/homebrew/opt/postgresql@17/bin`. If necessary, install with `brew install postgresql@17`. A Homebrew service/postinstall failure does not necessarily mean the binaries are unusable: check `/opt/homebrew/opt/postgresql@17/bin/postgres --version`. There is no need to start a Homebrew service for this workflow. On another installation, set `TRACEBACK_PG_BIN` to its binary directory.

From the repository root:

```sh
uv sync --extra test --locked
source .venv/bin/activate
python scripts/local_db.py init
alembic upgrade head
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

`init` creates a private `.local/traceback` directory, initializes PostgreSQL with SCRAM password authentication, starts the server, and creates the `traceback` database. It generates a database password and API bearer token without printing either. It writes a private `.env` only if none exists, using `TRACEBACK_DATABASE_URL` and `TRACEBACK_API_TOKEN`. An existing `.env` is preserved: ensure its connection URL matches this cluster if you supplied one yourself. Do not commit or share `.env` or `.local/traceback/credentials.json`.

Original attachment bytes are stored under `TRACEBACK_ASSET_DIR` (default `.local/traceback/assets`) using generated UUID keys. `TRACEBACK_MAX_UPLOAD_BYTES` defaults to 104857600 (100 MiB). Both paths and the generated credentials are ignored by Git. Keep free disk space available for originals and backups.

The generated role is the administrator of this isolated development cluster. This is a local development configuration, not a hosted deployment configuration. The socket is inside `.local/traceback`; server logs are in `.local/traceback/postgres.log`. If port 55432 is already occupied, stop and identify that process before starting another server. Do not delete a data directory to resolve a startup failure.

## Subsequent start and stop

```sh
source .venv/bin/activate
python scripts/local_db.py start
alembic upgrade head
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Stop the API with Ctrl-C, then stop PostgreSQL:

```sh
python scripts/local_db.py stop
python scripts/local_db.py status
```

`status` exits nonzero when the database is stopped. `start` is safe when this cluster is already running and verifies an authenticated connection. Data survives stopping the API, PostgreSQL, and the machine. Migrations must succeed before using API routes. Consult the README for the implemented health endpoints and API examples.

## Frontend (desktop web UI)

With the API running (above), start the Next.js frontend from `frontend/`:

```sh
cd frontend
npm install
cp .env.local.example .env.local   # then set TRACEBACK_API_TOKEN to the same value as the repo-root .env
npm run dev
```

Open **`http://localhost:3000`** — not `http://127.0.0.1:3000`. Next's dev server (Turbopack) blocks its own dev-only asset requests from non-`localhost` origins by default, which silently breaks every API call in development (screens appear stuck loading, with no console error). This only affects `next dev`; a production build (`npm run build && npm run start`) is unaffected.

The frontend never talks to the backend directly from the browser. `TRACEBACK_API_TOKEN` and `TRACEBACK_API_BASE_URL` are read server-side only, in `frontend/src/app/api/v1/[...path]/route.ts`, which proxies same-origin `/api/v1/*` requests to the real FastAPI backend with the bearer token attached. The token never reaches client-side JavaScript.

Run frontend tests and checks from `frontend/`:

```sh
npm run test   # Vitest: pure logic (task grouping/deadline formatting, API error handling) and component behavior
npx tsc --noEmit
npm run lint
npm run build  # production build + type check
```

Skills is a static admin page (planned-capabilities register); it does not call any backend endpoint. The personal memory graph and a mobile layout are not implemented — see `docs/personal-memory-plan.md`.

## Local MCP adapter

With the API running, start the stdio MCP adapter in another terminal:

```sh
.venv/bin/python -m traceback_mcp
```

It reuses `TRACEBACK_API_TOKEN` from `.env` and only ever talks to the API over loopback HTTP; it never opens a database connection itself. See [the MCP adapter: tool catalog, configuration, and Codex/Claude Code stdio setup](mcp-adapter.md).

## Separate integration database

Run `.venv/bin/pytest -q` after setup. The integration fixture uses the connection in `.env` (or an explicit loopback `TRACEBACK_TEST_ADMIN_URL`) to create a fresh UUID-named test database, applies migrations, and drops only that owned test database afterward. No manual test database setup is needed. The optional `create-test-db` command creates a persistent `traceback_test` database for manual experiments without resetting existing data; the automated fixture does not use it.

## Backup and verified restore

Stop the API and every other writer first, while leaving PostgreSQL running. The database dump is transactionally consistent; stopping writers also keeps manifest counts and any file copies aligned with that snapshot.

```sh
python scripts/local_db.py backup /tmp/traceback-backup-2026-09-14
python scripts/local_db.py restore /tmp/traceback-backup-2026-09-14 \
  --database traceback_restore_check \
  --assets /tmp/traceback-restored-assets-2026-09-14
```

Use a new destination each time. Backup refuses an existing destination and destinations inside `.local/traceback`. It saves `database.dump` in PostgreSQL custom format, an `assets/` copy, and `manifest.json` containing public-table row counts and file SHA-256 checksums. The assets directory is reserved for future attachment implementation; backing it up does not imply attachment endpoints are implemented. Credentials and `.env` are deliberately excluded. Keep backups private and copy important backups to durable storage; `/tmp` is only a convenient verification example.

Restore requires a new database name and a new asset directory. It refuses the live database, test database, and PostgreSQL system databases. It verifies copied asset checksums and every public-table row count against the manifest. This proves that the dump restores and that the recorded counts and files match; it does not replace API integration tests or a full comparison of every database value. Failed restores retain their new database/files for inspection and never remove live data. A backup without a manifest is incomplete.

Run a restore rehearsal before relying on the application for daily use. To inspect the restored database with the API, supply its URL to a separate API process, taking care to keep the usual development configuration intact. No automatic promotion, deletion, retention, or overwrite operation is provided. Logical dumps can be restored using compatible PostgreSQL tooling on another machine; preserve the backup's original files and metadata together.
