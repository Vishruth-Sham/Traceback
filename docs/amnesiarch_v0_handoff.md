# Amnesiarch — v0 Product & Architecture Handoff

## 1. What Amnesiarch Is

Amnesiarch is evolving beyond an Obsidian plugin.

It should be treated as a **personal memory / capture system** with its own canonical storage, API, and UI.

Obsidian can still exist as an optional integration or export target, but it should no longer be the primary product boundary.

The core idea:

> Capture thoughts and references with near-zero friction, preserve the raw source, interpret them into useful structured memory, and make that memory accessible from Amnesiarch itself and from external AI tools such as ChatGPT, Claude, and Codex.

---

## 2. Primary Input Paths

Amnesiarch should support three main ingestion paths in v0.

### 2.1 Voice / Typed Capture

User records a voice note or types a thought.

Examples:

- "I should read more about demand-filled look-aside caches."
- "Idea: GitHub gamification based on meaningful PRs."
- "Remember this for the Amnesiarch architecture."

Flow:

```text
Voice / Text
    ↓
Raw capture stored
    ↓
Voice transcribed if needed
    ↓
LLM interprets / atomizes
    ↓
Relevant note found or new note created
    ↓
Structured memory updated
```

The original raw capture should always be retained.

---

### 2.2 MCP Access

Amnesiarch should expose an MCP server so external AI clients can use the user's memory.

Examples:

- ChatGPT
- Claude
- Codex
- Cursor
- other MCP-compatible agents

Important distinction:

> MCP is not primarily another storage mechanism. It is an interface into the Amnesiarch memory system.

Example user interaction:

```text
User to ChatGPT:
"Add the above to my notes."
```

ChatGPT can then call Amnesiarch through MCP with the relevant content.

Initial MCP primitives can be minimal:

```text
add_memory(content, context?)
search_memory(query)
get_note(id)
update_note(id, content)
```

Potential later tools:

```text
delete_note(id)
list_recent_captures()
get_related_notes(id)
create_task(...)
get_context_for_topic(...)
```

---

### 2.3 Screenshot / Link + Description

The user can save:

- screenshot
- image
- URL
- article
- tweet/post
- arbitrary reference

For v0, Amnesiarch does **not** need to deeply understand the screenshot or webpage.

The user's description is treated as the primary semantic signal.

Example:

```text
Screenshot:
[agent execution UI]

Description:
"Interesting UI for showing agent execution history."
```

Stored representation:

```json
{
  "type": "reference",
  "description": "Interesting UI for showing agent execution history.",
  "asset_path": "...",
  "url": null
}
```

Later versions can enrich the capture with:

- OCR
- webpage extraction
- image understanding
- embeddings
- automatic summaries
- metadata extraction

But these are not necessary for v0.

The user's own description is often the highest-signal explanation of **why the reference mattered**.

---

# 3. Product Boundary

Amnesiarch should be its own application.

```text
                     Amnesiarch
                  canonical system

                         │
          ┌──────────────┼──────────────┐
          │              │              │
          ▼              ▼              ▼
     Amnesiarch UI      MCP         Obsidian
     web / mobile                  export / sync
```

Obsidian should be considered:

- optional
- an export target
- possibly a sync client later
- not the canonical source of truth

---

# 4. Why It Deserves Its Own UI

Amnesiarch now needs to represent concepts that do not map naturally to a normal notes editor:

- raw voice captures
- transcripts
- screenshots
- links
- processing state
- routing decisions
- interpreted notes
- source provenance
- undo
- resurfaced memories
- AI-generated relationships
- external MCP-originated memories

A dedicated UI can expose these directly instead of forcing them into folders/files.

The v0 UI does **not** need to become a Notion replacement.

Initial views can be limited to:

1. Capture
2. Inbox
3. Search
4. Notes

Example:

```text
AMNESIARCH

Capture
[ Speak ] [ Type ] [ Upload ]


INBOX

17:04  Voice   Thought about DGM
16:22  Image   Agent execution UI
14:31  Link    CDN architecture article


RECENTLY ORGANIZED

→ DGM / Self-improving agents
→ System Design / Caching
→ Amnesiarch / Product ideas


RESURFACED

"You had a similar idea 3 months ago..."
```

---

# 5. Storage Decision

For v0, use **Supabase as the canonical backend**.

Recommended components:

```text
Supabase
├── Postgres
│   ├── captures
│   ├── notes
│   ├── note_sources
│   └── embeddings        # later
│
├── Storage
│   ├── audio
│   ├── screenshots
│   └── attachments
│
└── Auth
```

The key principle:

> Markdown is the note format, but Markdown files do not need to be the primary database.

Store Markdown text inside Postgres.

---

# 6. Core Data Model

## 6.1 Captures

Captures represent the immutable or near-immutable raw input.

Suggested schema:

```sql
captures

id
source_type
raw_text
description
url
asset_path
created_at
processing_status
metadata
```

Possible `source_type` values:

```text
voice
text
screenshot
link
mcp
```

Examples:

### Voice

```json
{
  "source_type": "voice",
  "raw_text": "remember this idea about...",
  "asset_path": "audio/2026/09/06/abc.m4a"
}
```

### Screenshot

```json
{
  "source_type": "screenshot",
  "description": "Interesting UI for agent execution history",
  "asset_path": "screenshots/2026/09/06/xyz.jpg"
}
```

### MCP

```json
{
  "source_type": "mcp",
  "raw_text": "...",
  "metadata": {
    "client": "chatgpt"
  }
}
```

---

## 6.2 Notes

Notes represent the interpreted / organized memory.

Suggested schema:

```sql
notes

id
title
content_md
type
created_at
updated_at
metadata
```

Example:

```text
title:
Demand-filled look-aside cache

content_md:

## Demand-filled look-aside cache

A cache populated on demand instead of being proactively filled.

### Related

- CDN caching
- Redis
- cache invalidation
```

Potential note types:

```text
concept
idea
project
person
reference
decision
journal
task
general
```

Do not over-engineer the type system initially.

---

## 6.3 Note Provenance

Maintain explicit provenance between interpreted notes and raw captures.

Suggested schema:

```sql
note_sources

note_id
capture_id
```

Example:

```text
raw capture #3921
        │
        ▼
interpreted note #813
```

This allows the UI to answer:

- Where did this note come from?
- Which raw thought created this?
- Which screenshots contributed to this note?
- Which conversations updated this note?

---

# 7. Raw Capture vs Interpreted Memory

This separation is important.

Do not overwrite the raw user input with the AI interpretation.

Example:

```text
RAW CAPTURE

"yo remember that DGM paper, interesting idea where the
model modifies its own code..."

        ↓

INTERPRETED NOTE

# Dynamic model improvement

DGM explores agents that iteratively modify their own code
and evaluate variants.

Source:
voice_capture_2026-09-06_17-12
```

This gives Amnesiarch:

- auditability
- recoverability
- better future reprocessing
- provenance
- less risk of hallucinated AI summaries becoming the only record

---

# 8. Media Storage

Do not store large binary assets directly inside Postgres.

Use object storage.

Suggested paths:

```text
assets/
├── audio/
│   └── 2026/09/06/<uuid>.m4a
│
├── screenshots/
│   └── 2026/09/06/<uuid>.jpg
│
└── attachments/
    └── ...
```

The database stores only the relevant path and metadata.

---

# 9. Backend Architecture

Recommended v0:

```text
                    ┌───────────────────────┐
                    │       Clients         │
                    │                       │
                    │ Web UI                │
                    │ Mobile / PWA          │
                    │ MCP                   │
                    └───────────┬───────────┘
                                │
                                ▼
                       ┌─────────────────┐
                       │ Amnesiarch API  │
                       │    FastAPI      │
                       └────────┬────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                 │
              ▼                 ▼                 ▼
           Captures        Processing         Search
              │                 │                 │
              └──────────┬──────┴──────────┬─────┘
                         │                 │
                         ▼                 ▼
                  Supabase Postgres   Supabase Storage
```

Suggested endpoints:

```text
POST   /capture
GET    /captures
GET    /notes
GET    /notes/{id}
PATCH  /notes/{id}
GET    /search?q=...
POST   /notes/{id}/sources
```

Potential capture payload:

```json
{
  "source_type": "text",
  "raw_text": "Idea about MCP memory",
  "description": null,
  "url": null,
  "asset_path": null
}
```

---

# 10. Processing Pipeline

Initial pipeline:

```text
1. User captures something
2. Store raw capture immediately
3. Return success to user
4. Process capture
5. Classify / interpret
6. Atomize if necessary
7. Search for related existing notes
8. Decide:
   - append to existing note
   - update existing note
   - create new note
9. Store provenance
10. Surface result in UI
```

Important UX principle:

> Capture must succeed before sophisticated AI processing succeeds.

The user should never lose a thought because the LLM or routing layer failed.

---

# 11. Note Routing

Initial routing does not need to be perfect.

Possible logic:

```text
capture
    ↓
semantic search over notes
    ↓
top candidate notes
    ↓
LLM decision
    ├── merge
    ├── append
    └── create new note
```

If routing confidence is low:

- keep the item in Inbox
- ask for confirmation later
- or create a temporary note

Avoid blocking capture on routing confidence.

---

# 12. Search

v0 can start with standard database search.

Later add semantic search.

Potential progression:

```text
Phase 1
Postgres text search

Phase 2
Embeddings with pgvector

Phase 3
Hybrid search
keyword + semantic + metadata + recency
```

Do not introduce a separate vector database unless there is a strong reason.

---

# 13. MCP Architecture

The MCP server should call the same Amnesiarch backend used by the UI.

```text
ChatGPT / Claude / Codex
          │
          ▼
      MCP server
          │
          ▼
    Amnesiarch API
          │
          ▼
       Supabase
```

Do not create a second memory store specifically for MCP.

Potential v0 MCP tools:

```text
add_memory
search_memory
get_note
update_note
```

Possible example:

```text
User:
"Add the above to my notes."

AI client:
add_memory(
    content=<relevant conversation content>,
    context="conversation"
)
```

The Amnesiarch backend then handles routing and storage.

---

# 14. Obsidian Strategy

Obsidian should remain compatible but optional.

Recommended approach:

```text
Supabase
   ↓
export / sync
   ↓
Amnesiarch/
├── concepts/
├── projects/
├── ideas/
├── people/
└── references/
```

Each note can be exported as Markdown.

Example:

```text
concepts/demand-filled-cache.md
projects/amnesiarch.md
ideas/git-gamification.md
```

This provides an escape hatch from Amnesiarch.

Important principle:

> The user's knowledge should remain portable even if Amnesiarch disappears.

Possible command later:

```bash
amnesiarch export
```

Output:

```text
notes/
attachments/
metadata.json
```

A private Git repository can later be used as an additional backup if desired.

---

# 15. v0 Scope

Build only the minimum useful system.

## Required

### Capture

- typed capture
- voice capture
- screenshot upload
- link + description

### Storage

- Supabase Postgres
- Supabase Storage

### Processing

- raw capture preservation
- transcription
- simple classification
- note creation
- note merge/update
- provenance

### UI

- Capture
- Inbox
- Search
- Notes

### Integration

- basic MCP server

---

# 16. Explicit Non-Goals for v0

Do **not** build these yet:

- sophisticated knowledge graph
- automatic ontology
- full Obsidian bidirectional sync
- Notion-style collaborative editor
- perfect automatic routing
- custom vector database
- custom wearable
- deep screenshot understanding
- full webpage ingestion pipeline
- autonomous task orchestration
- complex agent framework
- elaborate folder hierarchy
- mobile native app unless necessary

Use the phone/browser as the initial capture hardware/interface.

---

# 17. Product Principles

## 17.1 Capture First

Saving the thought should be extremely fast.

AI processing happens after persistence.

---

## 17.2 Never Lose the Original

Raw user input should remain accessible.

AI interpretation is derived data.

---

## 17.3 User Intent Beats Automatic Extraction

For screenshots and links, the user's description is the most important field in v0.

---

## 17.4 One Canonical Memory Store

UI, MCP, and future integrations should all access the same backend.

---

## 17.5 Markdown-Compatible, Not Markdown-File-Dependent

Use Markdown as the content representation.

Do not make the filesystem the canonical database.

---

## 17.6 Portability

Everything should eventually be exportable into understandable formats:

- Markdown
- JSON
- original attachments

---

## 17.7 Avoid Infrastructure for Its Own Sake

Do not introduce Redis, queues, vector DBs, event buses, or microservices until there is a concrete need.

A monolithic FastAPI backend + Supabase is enough for v0.

---

# 18. Suggested Initial Stack

```text
Frontend
- Next.js
- responsive web UI / PWA

Backend
- FastAPI

Database
- Supabase Postgres

Object Storage
- Supabase Storage

Auth
- Supabase Auth

AI
- LLM provider abstraction
- speech-to-text provider

Semantic Search
- pgvector later

External AI Access
- MCP server
```

The MCP server can either:

1. live inside the same Python repository, or
2. be a very thin separate process calling the FastAPI backend.

Prefer the simpler option initially.

---

# 19. Suggested Repository Shape

```text
amnesiarch/
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── models/
│   │   ├── services/
│   │   │   ├── capture.py
│   │   │   ├── processing.py
│   │   │   ├── routing.py
│   │   │   ├── notes.py
│   │   │   └── search.py
│   │   ├── db/
│   │   └── main.py
│   │
│   └── tests/
│
├── frontend/
│   └── ...
│
├── mcp/
│   ├── server.py
│   └── tools/
│
├── migrations/
│
├── docs/
│
└── README.md
```

---

# 20. Core Mental Model

The simplest way to think about Amnesiarch:

```text
                    INPUTS

         voice       text
            \         /
             \       /
      screenshot   link
             \       /
              \     /
                MCP
                 │
                 ▼

              CAPTURE

                 │
          raw event stored
                 │
                 ▼

             INTERPRET

                 │
        atomize / classify
                 │
                 ▼

              ROUTE

           ┌─────┴─────┐
           ▼           ▼
      existing note   new note

           │           │
           └─────┬─────┘
                 ▼

              MEMORY

                 │
       ┌─────────┼─────────┐
       ▼         ▼         ▼
      UI        MCP      Export
```

---

# 21. One-Sentence Architecture Decision

> **Amnesiarch is a standalone personal memory system whose canonical Markdown-formatted notes and raw captures live in Postgres, whose media lives in object storage, whose own UI is the main browsing/editing interface, and whose memory is exposed to ChatGPT/Claude/Codex through MCP, with Obsidian treated as an optional export or integration layer rather than the primary application.**
