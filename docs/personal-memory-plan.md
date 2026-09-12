# Traceback — Personal Memory and Graph Plan

Date: 2026-09-12  
Status: Future phase, after the local backend and core UI work. This is a design proposal, not an implemented feature.  
Dependencies: [Backend plan](backend-plan.md), [UI plan](ui-plan.md).

## Purpose and boundary

Make Traceback useful both as a record of what the user knows and as context about the user that connected AI tools can retrieve. Combine source content, structured facts/preferences, and meaningful relationships. Keep the UI simple while providing a lightweight graph underneath.

Use the existing PostgreSQL store, captures, items, relationships, REST service, MCP adapter, revisions, and undo. Do not introduce a second memory database, a giant profile Markdown file, or a separate graph database for this phase. Notes can remain Markdown; facts and relationships are structured records.

Use the backend's file/time/source metadata from the start: distinguish source event time, original file times, ingestion time and later edits. Evidence points to a source revision and timestamp provenance; memory validity must not be inferred from upload time alone. Context results include relevant source dates and precision, and external visibility filtering also covers filenames, URLs and embedded metadata.

This phase must not delay the first backend. The foundation only needs stable IDs, source links, versioned writes, and ordinary item relationships. No Today view is reintroduced. Manual control remains mandatory.

## What counts as memory

| Class | Example | Behavior |
| --- | --- | --- |
| Knowledge | Notes explaining caching; a book observation | Keep original content and source links; index and connect it without duplicating every paragraph into a fact |
| Personal fact | The user's current laptop is an M5 Air | Record subject, fact, source, time and scope; allow correction and replacement |
| Preference | Prefers practical examples when studying | Preserve context; do not generalize it to every situation |
| Project decision | Traceback uses local PostgreSQL initially | Link to the project and evidence; distinguish a decided direction from a suggestion |
| Learning context | Currently studying database systems | Link user, topic/course and supporting notes; do not infer mastery from a saved article |
| Operational context | Open database assignment task | Read live task state from existing records; do not copy it into a permanent open-task fact |

Examples: “I might buy an M5 Air” is a possibility, not current ownership. A quote about someone's habits is not a fact about the user. A preference applying to coding does not automatically apply to learning or personal writing.

## Proposed data model

### Reuse existing identity

Entities are existing items: the user, books, projects, courses, topics, people and devices. Seed one `entity_type=person` item representing the user. Projects and books retain their existing IDs and types. About Me is a view over memories whose subject is the user, not a new top-level content category.

Introduce `type=memory` as an item subtype in this phase, with its own details table. It inherits item IDs, editing/version rules, archive state and history. Source notes remain existing notes. Memory items receive the applicable primary category or Inbox placement; the About Me view does not depend on that category.

| Table/change | Proposed fields and responsibility |
| --- | --- |
| `memory_details` | `item_id`, `subject_item_id`, `predicate`, nullable `object_item_id`, nullable typed `value_json`, `memory_kind`, nullable `scope_item_id`, optional scope qualifier, `assertion_status`, `origin`, `valid_from`, `valid_to`, `recorded_at`, optional `review_after`, `supersedes_item_id` |
| `memory_evidence` | Memory ID, source capture ID or source item ID, source item revision when applicable, locator/offset, evidence role (`supports`/`contradicts`), extraction run ID; derive display excerpts from retained evidence |
| `entity_aliases` | Entity item ID, alias, normalized alias; aliases help search but are not proof of identity |
| `memory_extraction_runs` | Source ID/revision, extractor/prompt/model version, idempotency key, state, lease/retry metadata, result IDs, errors |
| Existing `item_relations` | Keep organizational/associative links such as part_of, about, related_to; extend with origin, review state and evidence links for generated associations |
| Item/relation visibility | Proposed `local_only` / `external_allowed` access marker, enforced by service queries before external retrieval; do not equate unmarked with publicly shared |

A statement is either subject → predicate → entity or subject → predicate → typed value. Enforce exactly one of `object_item_id` and `value_json`. Example: user → uses_device → M5 Air entity; user → explanation_preference → “practical examples”, scoped to learning.

The memory statement is the authoritative semantic relationship. Graph rendering projects it as an edge labeled by predicate and memory ID; do not separately store an identical semantic edge in `item_relations`. Ordinary note→about→topic links remain ordinary relations.

### Status, time and vocabulary

- Assertion states: `proposed`, `accepted`, `rejected`, `superseded`, `needs_review`. Archive stays a separate item state.
- Origin: `explicit_user`, `source_extracted`, `inferred`, or `manual`. Accepted means usable under policy, not objectively proven true.
- `recorded_at` is when Traceback learned the statement; valid dates describe when it applied. Do not replace one with the other. Unknown validity stays unknown.
- Start with a controlled predicate set: uses_device, prefers, learning, working_on, project_uses, decided. Allow extensions through explicit admin changes later; the model cannot proliferate arbitrary near-duplicate predicates.
- Define allowed subject/object types and single-value versus multi-value behavior per predicate and scope. “Uses device” can have several answers. Do not infer that buying a laptop means discarding another.
- A model confidence score can be retained for debugging but must not be the sole acceptance rule.
- Fingerprint normalized statements including subject, predicate, object/value and scope to detect duplicate candidates. Repeated evidence from the same source is not independent confirmation.
- Enforce source and target existence, version checks, time-range consistency and valid transitions. Evidence created by direct manual entry can reference the user action rather than fabricate a capture.

## Automatic creation and linking

### Triggers

After a capture is interpreted or a user saves a meaningful note revision, enqueue extraction from that source version. Explicit “remember this” requests can trigger the same pipeline directly. Task events update operational retrieval from the task table; they do not require re-extracting a permanent statement on every checkbox change.

Process a bounded job per source revision, debounce rapid edits, and record completed runs. Memory outputs and generated summaries are not automatic new evidence sources: avoid loops where generated text repeatedly reinforces itself.

### Pipeline

1. Preserve the source and capture context, including timestamp and source identity.
2. The local model proposes memory candidates, named entities, relationships and evidence locations. Distinguish statements about the user from quotes, examples, possibilities, questions and third parties.
3. Search existing entities by stable ID/context, aliases and names. Ambiguous matches remain candidates; do not merge two people or projects merely because their names match.
4. Normalize candidate facts and scope. Search for duplicates, existing accepted statements and potential contradictions.
5. Validate targets, evidence and allowed schema in deterministic backend code. Exact snippets must match the specified source revision. Preserve uncertainty rather than invent missing dates or attributes.
6. Apply the acceptance policy below. Commit accepted memories, evidence, links, revisions and source processing results atomically through controlled tools.
7. Show a compact result: “Remembered your laptop” or “2 memory suggestions”, with source, View and Undo/Review.
8. Before a delayed job writes, check source revision and manual changes again. Stale jobs are cancelled/recomputed, not permitted to overwrite newer corrections.

Proposed runtime: reuse the local Qwen3.5-4B processor, with narrow extraction batches and bounded search/tool rounds. Whisper only handles audio input. No cloud fallback without a user-selected setting. Evaluate extraction separately from task routing before turning on broader automatic acceptance.

### Acceptance policy

| Candidate | Default behavior |
| --- | --- |
| Explicit first-person “remember…” with clear meaning, source and no conflict | Accept automatically, visibly record the result, allow edit/undo |
| Clear factual statement from a capture/note without an explicit remember request | Propose initially; automatic acceptance can be enabled later after evaluation |
| Inferred preference, personality trait, proficiency, or sensitive conclusion | Never silently accept; require review or omit unsupported candidates |
| Explicit project association supplied by the user | Create the association if the target is unambiguous |
| Automatically suggested topic/entity association | Proposed link until accepted or an evaluated policy explicitly allows it |
| Conflicting or ambiguously scoped fact | Keep candidate in review with the competing statements; do not silently choose the newest |
| Explicit correction of an identified fact | Atomically supersede the old statement, preserve its evidence/history, and accept the correction |

Expose an auto-memory toggle plus review mode. Manual add/edit/link/unlink works regardless of that toggle or model availability. Rejected candidates retain a minimal suppression marker so reprocessing the same unchanged source does not repeatedly suggest them; explicit user requests can override suppression.

## Updates, contradictions and forgetting

Example: “I switched from my old laptop to an M5 Air.” When the source explicitly establishes replacement, close the prior fact's validity and create the new one, linking it with supersedes. If it only says “I also have an M5 Air,” preserve both.

Edits to source notes mark dependent accepted statements for revalidation rather than silently rewriting them. Superseded, rejected, proposed and needs-review facts are excluded from default current-context answers. A separate review surface preserves their evidence. A review date requests a check; it does not mean a fact has automatically become false.

Manual corrections override stale automated work. Editing a statement and unlinking evidence are versioned, undoable actions. Entity merge is an explicit previewed operation with affected items shown; not automatic background cleanup.

Archive removes memory from default retrieval but keeps its ID and history. Permanent deletion follows the existing Archive flow, removes associated evidence/derived caches and stored copies of the deleted content, and respects relationships to other records. Default item deletion continues to preserve shared original captures.

Offer a separate “Forget this fact” flow that previews the difference between removing a derived memory and also removing its source content. A retained source can still contain the fact and must be disclosed in the preview. Full exclusion also needs derived-cache invalidation and suppression of re-extraction; matching broad natural-language facts is imperfect, so do not promise complete erasure while retaining sources. Existing backup retention remains separate.

## Retrieval: search plus graph context

Use keyword search over existing notes/items and accepted memory values first. Add embeddings later only if measured retrieval quality needs them. A graph complements content search; it does not replace it.

For a request such as “Help with my database assignment”:

1. Resolve the assignment/project/topic, using explicit IDs when supplied.
2. Retrieve matching current records and relevant note excerpts.
3. Expand one or two bounded graph hops for the course, relevant project decisions, and learning-scoped preferences.
4. Read current task completion/deadline state directly; exclude archived items and completed operations unless history is requested.
5. Filter by assertion state, validity, scope and external-access policy before including any record, edge, excerpt, count or summary.
6. Rank and deduplicate within a caller-requested size limit. Return only useful context, not the user's entire profile or whole graph.
7. Include canonical IDs, evidence links, relevant timestamps, reasons for inclusion and unresolved conflict indicators. Say when context is insufficient.

`get_context` returns a structured context bundle first: personal context, project/topic knowledge, live tasks, sources and conflicts. A generated prose summary is optional and must cite those records; it does not become a new accepted memory.

## Desktop UI

Add a Memory destination after this phase ships. Keep existing category/project pages and Tasks intact. Memory has a simple list-first layout with About Me, Knowledge/Decisions, Review, and an optional Graph tab. These are views over records, not competing category trees.

### Memory list and About Me

Group personal memories by preferences, background, current setup and learning context. Each row shows the statement, scope, current/review state, last update and source access. Add, edit, archive, and visibility controls must be obvious. Do not make the user open a graph to correct a fact.

### Memory detail

Show editable subject, predicate, object/value, scope and validity, plus evidence and change history. Allow attaching/removing evidence, linking/unlinking related entities, correcting/superseding, archive/restore and confirmed permanent deletion. Display an explanation of automatic creation with model/run attribution, not hidden model reasoning.

### Review

Review proposed facts and links with Accept, Edit then accept, Reject, and Resolve conflict. Include source excerpts and competing statements. Keep this separate from Inbox placement review: classifying a note does not approve every fact inferred from it, and moving an item to Other does not accept a memory.

### Graph explorer

Start centered on the user or selected project/topic, with a bounded neighborhood. Distinguish entities, notes and tasks visually; label edges in plain language. Click an edge to open the memory/relationship and its evidence. Expand neighbors on demand, filter by relation/state/date and provide a readable list equivalent.

Manual Add link, Edit link, Remove link and Add memory must work here too. Layout changes are visual only and do not change category membership. Preserve IDs across list, graph and project screens. Avoid opening with every node in one unreadable diagram.

### Existing screen integrations

- Capture result: visible memory-created or review-needed feedback, separate from task/note creation.
- Note/project detail: Related section and linked memories, with Add link and source/history access.
- Tasks: optional linked course/project/context; no separate duplicate memory version of the task.
- Skills: Memory extraction capability, enable/disable, review policy, last run/errors and manual retry.
- Search: distinguish accepted memories, ordinary notes, tasks and historical results.

Acceptance includes all creation/edit/review/link/archive flows with the local model stopped.

## REST and MCP extensions

All routes below are proposed under `/api/v1`, sharing the existing API service, IDs, authentication, versions, idempotency and errors. MCP adapters never gain direct database write access.

| Purpose | REST | MCP |
| --- | --- | --- |
| Save an explicit memory request | `POST /memory/remember` | `remember` |
| Create a structured manual memory | `POST /memories` | `create_memory` |
| List/filter | `GET /memories` | `list_memories` |
| Search knowledge and personal memory | `GET /memory/search` | `search_memory` |
| Read fact/evidence/history | `GET /memories/{id}` and existing history routes | `get_memory` |
| Edit/correct/supersede | `PATCH /memories/{id}`, `POST /memories/{id}/supersede` | `update_memory`, `supersede_memory` |
| Resolve existing entities | `GET /entities?query=...` | `find_entities` |
| Create/update entity | Existing item endpoints | Existing create/update item tools |
| Bounded neighborhood | `GET /memory/graph?root_id=...&depth=...` | `get_related_memory` |
| Create/edit/remove association | Existing relation routes plus versioned PATCH | `link_items`, `update_link`, `unlink_items` |
| Add/remove evidence | `POST /memories/{id}/evidence`, `DELETE /memories/{id}/evidence/{evidence_id}` | `add_memory_evidence`, `remove_memory_evidence` |
| Compose relevant context | `POST /memory/context` | `get_context` |
| List review candidates | `GET /memory/review` | `list_memory_suggestions` |
| Review a candidate | `POST /memories/{id}/review` | `review_memory` |
| Request extraction | `POST /memory/extractions` | `extract_memories` |
| Poll extraction | `GET /memory/extractions/{id}` | `get_memory_extraction` |
| Archive/restore/delete | Existing item archive/restore/delete routes | Existing item lifecycle tools |
| Visibility | Versioned item/relationship update | `set_memory_visibility` as a convenience wrapper |

`remember` preserves the supplied raw input and returns saved versus processed state explicitly. It is distinct from a structured manual memory create. Extraction returns proposed/accepted IDs and unresolved issues, not just a success string. Retrieval supports category, subject, project, scope, as-of time, history and result-budget filters. Graph expansion enforces server-side depth/node limits.

External write permission to create suggestions does not grant permission to accept them. Review and visibility changes require the relevant user/admin action policy. Automatic capture tools cannot approve their own unsupported proposals or make private memories externally available.

## External access controls

Proposed default: new personal memory is local-only until the user enables sharing for it or a selected collection. Final defaults should be chosen before exposing this phase to external clients. Store visibility per item with optional relation restrictions; stricter source evidence restrictions also apply to derived memory output unless the user explicitly approves a redacted shareable version.

External MCP and REST access must use a distinct restricted credential/context from the local admin UI/runner. A caller cannot gain admin access by setting `audience=local`. The server derives access from the authenticated credential.

Apply visibility to searches, direct reads, graph endpoints, sources, history, related IDs, context summaries and existing generic item APIs. A memory-only filter is insufficient because generic `get_item` could otherwise bypass it. Prefer non-disclosing not-found responses for inaccessible IDs. Validate retrieval with private and shared records mixed in the same graph.

This controls what tools can retrieve, not what an external AI provider does after it receives allowed content. Keep local model processing local; never silently switch providers.

## Implementation sequence and acceptance

1. **Foundation gate:** existing CRUD, Tasks, capture/source storage, versions, archive and local REST/MCP pass their acceptance flows.
2. **Memory schema and manual control:** introduce memory items, predicates, evidence, statuses and aliases. Build list/About Me/detail CRUD and direct structured APIs. Verify scope, dates, evidence and correction behavior.
3. **Search and external access:** implement visibility enforcement across all old/new endpoints, memory search and structured context bundles. Verify no private data leaks via graph counts, history, evidence, generic item reads or summaries.
4. **Local extraction:** connect bounded Qwen jobs, deduplication, entity resolution and Review. Test explicit facts, quotes, hypotheticals, preferences, updates, ambiguous names, stale jobs, restart/retry, rejection suppression and manual override.
5. **Graph UI and context expansion:** provide bounded graph exploration, editable links and one/two-hop retrieval. Verify IDs and source evidence match the list/detail screens.
6. **Daily-use evaluation:** run real captures and context requests through UI plus local Codex/Claude Code. Assess unsupported accepted facts, duplicates, wrong merges, stale context, missed relevant knowledge, latency and memory usage. Tighten acceptance policy before enabling broader automatic creation.

Representative end-to-end case: capture “Remember that I prefer examples while studying databases”; inspect its source-linked scoped memory; ask an external client for database-assignment context; verify the preference appears only when sharing permits it; correct the preference manually; confirm a stale extraction cannot undo the correction; archive it and verify default retrieval excludes it.

## Open decisions for this future phase

- Initial sharing defaults and per-client permissions.
- Exact predicate vocabulary and automatic acceptance policy after evaluation.
- Entity merge UI and review rules; no automatic destructive merges initially.
- Retention and forgetting UX across sources, extraction suppression, caches and backups.
- Whether keyword plus bounded graph retrieval needs embeddings based on observed failures.

None of these requires a graph database or blocks building the first local backend.
