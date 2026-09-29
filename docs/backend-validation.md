# Traceback validation record

Updated: 2026-09-26
Current schema head: `20260915_0006`
Current verified application-code commit: `916d557`

This page records observed validation, not a promise that optional local-model quality will remain constant. Earlier milestone totals of 54, 123, 202, and 22 tests were valid at their respective implementation stages but are superseded by the final baseline below.

## Current verified baseline

The final pre-push run on 2026-09-15 completed successfully:

| Check | Result |
| --- | --- |
| `.venv/bin/pytest -q` | **219 passed**, one upstream Starlette/AnyIO deprecation warning |
| `npm test -- --run` | **29 passed** across six frontend test files |
| `npm run typecheck` | Passed |
| `npm run lint` | Passed |
| `npm run build -- --webpack` | Passed; 13 application routes generated |
| `uv lock --check` | Passed using a writable temporary cache |
| `git diff --check` | Passed |
| Staged credential-pattern scan | No matches |

The default Turbopack production build could not bind an internal temporary port in the managed verification sandbox. Re-running the same production build with Next.js webpack completed successfully. This was an environment restriction, not a source compilation failure.

## Coverage represented by the suite

- Real PostgreSQL migrations and isolated throwaway test databases rather than SQLite substitutes.
- Stable fixed-category seeds and database constraints for valid task and placement rows.
- Canonical item CRUD, partial edits, deadline validation and ordering, completion/reopening, pagination, and Inbox behavior.
- Expected-version conflicts, idempotent creates/retries, revision history, supported undo, and rejection of stale writes.
- Project/folder containment, single-parent enforcement, cycle prevention, descendant category propagation, atomic create-in-container, and non-cascading archive/deletion behavior.
- Archive-first permanent deletion for items, captures, and assets, including reference-conflict protection.
- Immutable capture originals, timestamp provenance, corrections, leases/generations, retry/failure behavior, manual interpretation, source links, and rollback on invalid operations.
- Local attachment upload metadata, checksums, byte persistence, download, references, archive/restore, and deletion rules.
- Task quick add: capture-first persistence, exactly one structured task, deadline parsing contract, manual fallback, and stale-work fencing.
- Note quick add: durable `awaiting_review` proposals, canonical location validation, manual destination override, one-note acceptance, corrections, provenance, and conflict behavior.
- MCP argument shaping, stdio protocol operation, REST error mapping, path/ID validation, destructive confirmation, and real HTTP-to-PostgreSQL acceptance.
- Frontend task grouping, API errors, task rows, relations, task quick add, and note quick add component behavior.

## Runtime checks performed during implementation

- Fresh migration upgrade, downgrade to base, and upgrade again passed at the earlier schema stages; the live local database was subsequently migrated through `20260915_0006`.
- Real Uvicorn checks returned healthy liveness/readiness, authenticated categories, and rejection of unauthenticated item access.
- A PostgreSQL/assets backup was restored into a separate database and asset directory; table row counts and recorded SHA-256 checksums matched.
- whisper.cpp 1.9.4 with Whisper small and Ollama 0.30.11 with `qwen3.5:4b` Q4_K_M were installed and exercised locally. Synthetic smoke/latency checks passed where recorded in [local-models.md](local-models.md).
- The desktop UI was driven against the real API and database for navigation, tasks, typed capture, Inbox classification, projects, archive/restore, and layout checks documented in [design-qa.md](../design-qa.md).

## Voice command slice (2026-09-26)

Automated evidence for the review-first voice feature, run against throwaway PostgreSQL databases with stubbed Whisper/Qwen and fake browser recorder APIs: pure policy tables (dates, weekday semantics, timezones/DST gaps, destinations, intent, disposition), PostgreSQL contract tests (idempotent atomic ingest including 20 concurrent same-key requests, digest/size/type/disk/ENOSPC/database-failure cleanup, capability toggling, transcript checkpoint without a version bump, forged-evidence rejection, accept/override audit, overdue confirmation, stale-generation fencing, `capture_only` Inbox lifecycle, disabled-mode escape hatch, `claim-next` fairness and no double claim), processor stage-order/failure-retention tests plus a real-HTTP round trip with real ffmpeg normalization, MCP parity/exclusion tests, Vitest tests for the proxy body cap, recorder state machine, mutex, retained-blob retry, review card, entry points, and Inbox. Exact counts are in [current-status.md](current-status.md).

### Voice: not proven, manual Phase 0 validation still required

Real-microphone recording in Chromium/Safari and the MIME types they actually emit, real Whisper/Qwen quality on personal speech (no corpus exists and no scoring script was written), end-to-end latency/thermal/battery behaviour, network-off operation, real Next-proxy memory with a 10 MB body, and the kill/disk-full/toggle drills. See the checklist in [features/voice-commands.md](features/voice-commands.md#what-remains-manual-phase-0-validation).

## What was not proven

- Representative personal recording/transcription quality, multilingual quality, and reliable semantic classification quality were not benchmarked.
- Audio capture could not be exercised with a real microphone in the headless design-QA browser.
- The project-local MCP implementation passed protocol and acceptance tests, but each developer-owned Codex/Claude client installation still needs its own configuration smoke test.
- No hosted deployment, remote authentication, mobile UI, reminders, recurrence, automatic Inbox aging, or personal-memory graph was validated because those capabilities are not implemented.

## Reproduce the checks

Start the private PostgreSQL cluster and apply migrations as described in [local-development.md](local-development.md), then run:

```sh
.venv/bin/pytest -q

cd frontend
npm test -- --run
npm run typecheck
npm run lint
npm run build -- --webpack
```

Real-model tests remain availability- and output-dependent smoke tests. Invalid model output is expected to be rejected while preserving the original capture; it must not be interpreted as a capture-persistence failure.

## Repository hygiene

The verified commit excludes `.env`, `.env.local`, `.mcp.json`, `.local/` PostgreSQL/assets state, recordings, model weights, virtual environments, build output, and dependency directories. Commit `916d557` was pushed to `origin/main`; this supersedes earlier milestone notes saying no commit or push had occurred.
