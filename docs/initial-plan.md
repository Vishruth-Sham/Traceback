# Traceback — Current Implementation Plan

Updated: 2026-09-26
Status: The local foundation is implemented and pushed through commit `916d557`: schema/REST, capture/provenance and attachment storage, nested folders, bounded local processing, local stdio MCP, the desktop UI, capture-first task quick add, and reviewed note quick add. See [current status](current-status.md), [implemented API](backend-api.md), [MCP adapter](mcp-adapter.md), [local development](local-development.md), and [validation](backend-validation.md).

## Current specifications

1. [Backend plan: data model, local PostgreSQL, REST and MCP](backend-plan.md)
2. [UI plan: desktop screens, behavior, API connections and validation](ui-plan.md)
3. [Future personal memory: automatic extraction, graph, UI, REST and MCP](personal-memory-plan.md) — after the core backend/UI.

These plans supersede earlier Supabase-first, Today-view, planned-date, and mobile requirements. Original handoffs and UI mockups are preserved as references; latest user decisions take precedence.

## Confirmed direction

- Traceback is a personal tool for its sole user/admin, used on a PC.
- First version runs locally: PostgreSQL, local assets, REST API, and MCP adapters for local Codex/Claude Code. Hosted storage such as Supabase comes later.
- Fixed categories: Health & Food, Personal Growth, Books, Learning, Projects, Other. Other replaces Everyday Life.
- One canonical ID per item/task across UI and integrations.
- Manual control is mandatory throughout: add, edit, organize, link/unlink, complete/reopen, archive/restore, and permanently delete supported content directly in the UI. No AI or MCP dependency for these actions.
- Tasks is the only task view. Sort open tasks by due date, overdue first, undated last. No Today view or separate planned date.
- Inbox holds unresolved captures/items. Manual Move to chooses a destination. Automatic movement to Other remains disabled until an inactivity interval is explicitly selected.
- Preserve original captures, source links, revision history and undo.
- Archive first; permanent deletion from Archive is explicit. Completion is separate from archive.
- Keep Skills as an intentional admin surface and backlog of capabilities.

## Delivered foundation

The first useful delivery is complete: local REST and MCP can create/read/edit supported items, original captures and provenance are preserved, and the desktop UI is wired to those operations with deadline ordering, Inbox routing, archive/restore, and failure recovery.

Use local whisper.cpp with Whisper small and Ollama `qwen3.5:4b` Q4_K_M for in-app capture processing, with a bounded runner using shared REST business rules. The initial runtime settings were smoke-tested on the base M5 MacBook Air; representative personal-content quality still needs later evaluation. Codex/Claude Code are optional external clients through the implemented local MCP adapter. Richer tracking and individual Skills follow in subsequent increments.

## Personal memory phase after the foundation

Add source-backed personal facts/preferences and project/learning context alongside existing knowledge. Use PostgreSQL memory records and relationships, automatic extraction with review, manual editing, a bounded graph explorer, and controlled REST/MCP retrieval. The separate [personal memory plan](personal-memory-plan.md) defines this future phase; it does not block the first backend.

## Hosted migration

Retain portable PostgreSQL migrations and stable IDs, isolate asset storage, then migrate the database/assets and add hosted authentication when needed. Verify migration and rollback rather than assuming deployment only changes a URL.

## References

- [Historical expanded product handoff using the old Amnesiarch name](amnesiarch_v0_handoff_updated.md)
- [Historical original product handoff using the old Amnesiarch name](amnesiarch_v0_handoff.md)
- [Claude-generated UI reference](../initial%20UI%20views/Traceback%20Main%20Page%20%28standalone%29.html)

## Progress

- [x] Preserve handoffs and review first-pass UI.
- [x] Record personal-use and Tasks-only decisions.
- [x] Draft local backend data model and REST/MCP contracts.
- [x] Draft desktop UI plan.
- [x] Implement core schema and local REST backend for notes, tasks, and projects.
- [x] Implement captures, provenance, attachments, and durable processing state.
- [x] Implement and smoke-test the bounded local Whisper/Qwen processor.
- [x] Implement the local MCP adapter, with unit, stdio-protocol, and real-HTTP/PostgreSQL acceptance tests.
- [ ] Configure and verify both local MCP clients (Codex, Claude Code) against a developer's own installation; project-local example configs exist under `docs/examples/` but have not been wired into either client as part of this change.
- [x] Connect and verify the UI for the first useful slice (navigation, Tasks, Inbox classification, categories, Projects/membership, typed/audio capture, archive/restore). See [design-qa.md](../design-qa.md).
- [x] Implement capture-first free-text task creation with structured local-model output and a manual fallback.
- [x] Implement reviewed note quick add with a canonical location catalog, durable proposal state, manual destination selection, and one-note acceptance.
- [ ] Run a fresh daily-use browser/API/MCP acceptance pass and fix concrete integration/usability gaps before selecting the next large feature.
