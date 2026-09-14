# First backend milestone validation — 2026-09-14

## Current regression status

Later folder/UI/free-text-task hardening adds PostgreSQL migration `20260915_0005`, which enforces one `part_of` parent per item without silently rewriting ambiguous existing data. Database-backed tests cover replacement moves, category moves that detach containment, descendant placement propagation, archived-parent root visibility, atomic create-in-folder, and the task-only quick-add contract. Processor tests cover that profile and bounded normalization of Qwen's occasional trailing Markdown fence/date-only timezone combination. Frontend tests cover capture-first quick add and reuse of its idempotency key after an uncertain response; the production Next.js webpack build succeeds without network font access.

Reviewed note quick add advances the expected schema head to `20260915_0006`, adding durable proposal state and `awaiting_review` processing.

Run the current checks rather than relying on the historical counts below:

```sh
.venv/bin/pytest -q
cd frontend
npm test -- --run
npm run typecheck
npm run lint
npm run build -- --webpack
```

The real-model tests are availability- and output-dependent quality smoke tests. Invalid model output is rejected and leaves the original capture recoverable; it must not be treated as a persistence failure.

Latest run on this machine: backend/processor/MCP **202 passed** (including available local Qwen smoke tests); frontend **22 passed**; TypeScript, ESLint, `git diff --check`, and the offline webpack production build passed. One upstream Starlette/AnyIO deprecation warning remains.

Confirmed machine: Apple M5, arm64, 16 GiB unified memory. Python 3.14.6, uv 0.11.21, and PostgreSQL 17.11 were used. Python dependencies are pinned in `uv.lock`. whisper.cpp 1.9.4 with Whisper small and Ollama 0.30.11 with `qwen3.5:4b` Q4_K_M were installed and exercised locally; see `docs/local-models.md` for measurements and the explicit quality limitations.

## Checks completed

- 54 pytest tests passed. The 21 backend tests use a newly created PostgreSQL database, not SQLite or mocked persistence; the fixture drops only its own UUID-named database. The remaining processor tests include validation/unit coverage, a real HTTP-to-PostgreSQL runner integration, and gated real local-model smoke tests (both ran on this machine).
- Fresh migration upgrade, downgrade to base, and upgrade again passed; fixed category seeds survived reinitialization with stable IDs.
- Canonical task lifecycle, task ordering, partial deadline edits, validation, simultaneous edits, stale versions, idempotent retries, and concurrent idempotent creates passed.
- Project move/link/unlink, atomic version conflicts, non-cascading project archive/deletion, move undo, and rejection of undo after later edits passed.
- Archive-before-delete and removal of content revisions and stored idempotent response content passed. PostgreSQL rejected invalid placement and task rows missing task details.
- Real Uvicorn HTTP checks on `127.0.0.1:8000`: liveness 200, authenticated readiness 200, six category seeds 200, unauthenticated item request 401.
- After migrations `20260914_0002` and `20260914_0003`, a fresh backup restored into `traceback_restore_capture_20260914`; every public-table row count and every recorded asset SHA-256 checksum matched. The application asset directory was empty at backup time, while non-empty asset byte persistence and deletion are covered in isolated PostgreSQL/API tests.
- Python compilation, `git diff --check`, and ignore checks for `.env`, credentials, and `.venv` passed.
- Capture tests cover immutable originals and timestamp distinctions, corrections, processing failure/retry, stale leases, atomic manual interpretation, provenance, rollback, partial-undo refusal, upload checksums/bytes, and reference-aware deletion.

Two test-library deprecation warnings remain (Starlette/httpx and AnyIO); tests pass. No secrets, runtime data, recordings, or weights were added to Git. No commit, push, or deployment was performed.

## Local setup note

Homebrew installed PostgreSQL binaries but failed its service/postinstall step (`stop_timeout` incompatibility). The bottle also lacked versioned resource links expected by `pg_config`. The existing installation was repaired by adding `/opt/homebrew/share/postgresql@17` and `/opt/homebrew/lib/postgresql@17` links to its verified 17.11 resource directories. Traceback uses `pg_ctl` through its own script and does not depend on Homebrew services. This machine-specific repair is not required on a healthy PostgreSQL installation.

## Local MCP adapter validation — 2026-09-14

The local stdio MCP adapter (`traceback_mcp`, see `docs/mcp-adapter.md`) is implemented and tested against this same real PostgreSQL/HTTP stack, on top of the 54 backend/processor tests recorded above:

- 69 additional `traceback_mcp` tests passed: 22 argument-shaping unit tests against a fake REST client, 4 REST-client failure-handling unit tests (read timeout, malformed JSON on a 2xx response), 33 focused regression tests (cwd-independent `.env` resolution; path-injection-shaped and otherwise malformed resource IDs rejected by MCP schema validation before any REST call), 9 real HTTP-to-PostgreSQL acceptance tests under a real `uvicorn` server, and 1 subprocess stdio-protocol test using the official `mcp` client SDK.
- Full suite: `.venv/bin/pytest -q` → **123 passed** (54 pre-existing + 69 new). `uv lock --check` confirms `uv.lock` still matches `pyproject.toml`, including the narrowed `mcp>=2.2.0,<2.3.0` pin.
- An earlier draft of this milestone's own documentation mis-stated the pre-existing count as 64; the correct, verified count is 54 (`pytest --collect-only` on the non-MCP test files), and this note exists so that mistake is not repeated.

## Remaining milestones

Next: evaluate Whisper/Qwen on approved representative personal samples and configure/verify each developer-owned MCP client using the project-local examples. Automatic Inbox aging, reminders, and the personal-memory graph remain unimplemented; the core desktop UI is now present.
