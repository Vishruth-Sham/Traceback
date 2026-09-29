# Traceback current status

Updated: 2026-09-26  
Application implementation reviewed from baseline commit `916d557` on `main`.

This page is the canonical snapshot of what exists now. The plan documents describe product direction; the historical Amnesiarch handoffs and HTML exports are reference material only.

## Implemented

- Local PostgreSQL 17 schema and Alembic migrations through `20260915_0006`.
- Six read-only seeded categories: Health & Food, Personal Growth, Books, Learning, Projects, and Other.
- Canonical `note`, `task`, `project`, and `folder` items with UUID identity shared by UI, REST, and MCP.
- Task deadlines, open/completed views, complete/reopen, and overdue/upcoming/undated ordering. There is no Today view or planned-date field.
- Inbox placement, keyword search, nested single-parent folders, project membership, `about`/`related_to` links, history, and supported undo operations.
- Version-checked manual create, edit, append, move, link/unlink, archive/restore, and archive-first permanent deletion.
- Immutable captures, versioned corrections, source provenance, timestamp distinctions, local attachment bytes/metadata, and durable processing state.
- Capture-first task quick add that asks local Qwen for exactly one structured task and retains a manual fallback.
- Reviewed note quick add that saves the exact note, requests a bounded local-Qwen location proposal, and lets the user accept or replace it before creating one canonical note.
- A bounded local processor using loopback REST. Typed captures skip transcription; audio can use local whisper.cpp. There is no cloud-model fallback.
- **Opt-in, review-first voice commands** ([details](features/voice-commands.md)), off by default (`TRACEBACK_VOICE_COMMANDS_ENABLED`): atomic idempotent audio ingest, ffmpeg normalization, transcript checkpoint before interpretation, strict Qwen slot extraction, a backend-owned deterministic policy (grounding, intent, dates/timezones, destination resolution, warnings), stored proposals, manual accept/override with server-side audit and overdue confirmation, stale-generation fencing, capability discovery, a fair `claim-next` queue, one global voice panel with recording and typed-command entry, a shared review card, and typed MCP parity. Auto-apply is not implemented and cannot be enabled. The retired auto-interpreting audio path is frozen to review.
- A REST-only local stdio MCP adapter for Codex and Claude Code. It shares backend rules and never accesses PostgreSQL directly.
- A desktop Next.js UI for Tasks, Inbox, categories, projects/folders, notes, search, archive, Skills, capture, and manual organization.
- Local startup, lifecycle, backup, and verified-restore tooling.

## Verified after the voice-command slice (2026-09-26)

- `.venv/bin/pytest -q`: **379 passed** (219 before; four existing legacy `general`-audio tests were rewritten because the plan freezes that path to review, and a net 160 tests were added across policy tables, PostgreSQL contract, processor, and MCP).
- `npm test`: **98 passed** across 11 Vitest files; `npm run typecheck`, `npm run lint`, and `npm run build -- --webpack` passed.
- `git diff --check` and `uv lock --check` passed. No database migration was needed.
- These use throwaway PostgreSQL databases, stubbed Whisper/Qwen, and fake browser recorder APIs. They prove the contract, not recognition quality or real-microphone behavior.

## Earlier verified baseline

The final pre-push verification on 2026-09-15 produced:

- `.venv/bin/pytest -q`: **219 passed**, with one upstream Starlette/AnyIO deprecation warning.
- `npm test -- --run`: **29 passed** across six frontend test files.
- `npm run typecheck`: passed.
- `npm run lint`: passed.
- `npm run build -- --webpack`: passed.
- `uv lock --check`: passed with a writable temporary cache.
- `git diff --check` and staged credential-pattern checks: passed.

The voice-command slice above was added after that commit and is uncommitted in the working tree. The local application database and asset directory remain present, but the frontend, API, processor, and project-local PostgreSQL server are currently stopped.

## Deliberately deferred

- Automatic Inbox aging to Other, because no inactivity interval has been selected.
- Reminders, notifications, and recurrence.
- Personal facts/preferences, memory extraction, evidence review, context retrieval, and graph exploration.
- Recipe, calorie, goal-progress, reading-status, and reusable-list schemas/screens.
- Hosted deployment, hosted authentication, Supabase migration, and mobile UI.
- Automatic folder creation or automatic acceptance of note-placement proposals.

## Known limitations

- Whisper small and `qwen3.5:4b` were installed, exercised, and latency/memory measured on this Mac in isolation, but representative personal-content quality was not benchmarked, and the new voice chain (browser recording → ffmpeg → Whisper → Qwen slots → backend policy) has not been measured at all.
- **Voice manual validation still required** and not claimed: real Chromium/Safari microphone recordings and their MIME types, the ≥150-utterance corpus and its scoring (no scoring script exists), p95 latency/thermal/battery, network-off proof, real Next-proxy memory at 10 MB, and the kill/disk-full/toggle drills. See [the checklist](features/voice-commands.md#what-remains-manual-phase-0-validation).
- Voice features not built: auto-apply, organization/mutation voice intents and multi-intent splitting, the asset reconciler and storage summary/guided reclaim view, thermal/low-power deferral, and offline evaluation scripts.
- MCP client configuration examples exist, but each developer-owned Codex/Claude installation still needs an explicit end-to-end configuration check.
- The Skills page is intentionally a static capability register, not proof that every listed skill exists.
- Current search is keyword-based. Semantic/vector retrieval belongs to the later memory phase only if measured need justifies it.

## Recommended next milestone

Run the existing application as a daily-use system and perform a focused browser/API/MCP acceptance pass on manual CRUD, task quick add, note quick add, folder placement, archive/restore, and failure recovery. Fix concrete integration or usability gaps before starting reminders or the personal-memory graph. Voice is now usable behind an off-by-default switch; complete its manual validation checklist, take a verified backup, and use it review-first before enabling it for daily use.

## Documentation map

- [Local startup and operations](local-development.md)
- [Implemented REST API](backend-api.md)
- [Backend specification and roadmap](backend-plan.md)
- [Desktop UI specification](ui-plan.md)
- [MCP architecture and setup](mcp-adapter.md)
- [MCP tool usage reference](mcp-tool-reference.md)
- [Voice commands (implemented, review-first)](features/voice-commands.md) and its [planning document](features/voice-command-capabilities-plan.md)
- [Local model implementation and measurements](local-models.md)
- [Validation history](backend-validation.md)
- [Future personal-memory phase](personal-memory-plan.md)
