# Historical handoff: Amnesiarch v0 (expanded draft)

> **Historical reference only.** This document predates the Traceback name and current product decisions. Do not treat its Supabase/hosting, navigation, category, mobile, or feature statements as current requirements. Start with [current-status.md](current-status.md), [initial-plan.md](initial-plan.md), [backend-plan.md](backend-plan.md), and [ui-plan.md](ui-plan.md). The old product name below is preserved only to keep the original handoff intact.

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


---

# 22. Agentic Capture Architecture

Amnesiarch should become agentic **after the raw capture is safely persisted**.

The user should be able to speak or type naturally without choosing a destination or action manually.

Example:

```text
"Remember that for Amnesiarch we should keep raw captures
separate from interpreted notes, and add it to the architecture doc."
```

Desired flow:

```text
Mic / text
    ↓
Speech-to-text if needed
    ↓
RAW CAPTURE STORED IMMEDIATELY
    ↓
Memory Agent
    ↓
Agent determines intent
    ↓
Agent searches existing memory
    ↓
Agent chooses an action
    ├── append to an existing note
    ├── update an existing note
    ├── create a new note
    ├── create a task
    ├── create a reminder
    ├── update a list
    ├── save a reference
    ├── attach to a project/entity
    └── leave in Inbox if uncertain
```

Core rule:

> **Agentic reasoning, deterministic execution, immutable raw capture.**

The LLM should reason about what to do, but all writes should happen through controlled application tools.

# 23. Agent Tool Surface

The agent should not have arbitrary SQL/database access. Give it a small deterministic toolbelt.

Initial tools:

```text
search_notes(query)
read_note(id)
create_note(...)
append_note(...)
update_note(...)
create_task(...)
update_task(...)
create_reminder(...)
update_reminder(...)
create_list(...)
update_list(...)
create_entity(...)
update_entity(...)
save_reference(...)
get_recent_captures(...)
link_source(note_id, capture_id)
```

Potential later tools:

```text
search_web(...)
read_url(...)
analyze_image(...)
schedule_reminder(...)
find_related_entities(...)
resurface_memory(...)
```

Architecture:

```text
                Memory Agent
                     │
                  tool calls
                     │
      ┌──────────────┼──────────────┐
      ▼              ▼              ▼
 search_notes   append_note    create_task
      │              │              │
      └──────────────┼──────────────┘
                     ▼
              deterministic API
                     ▼
                  Supabase
```

The backend should enforce schemas, validation, provenance, authorization, lifecycle rules and undo.

# 24. Agent Decision Hierarchy

```text
Capture
  ↓
Can explicit intent be determined?
  │
  ├── YES → perform requested action
  │
  └── NO
      ↓
Search relevant memory
      ↓
Can it be confidently routed?
  │
  ├── YES → update/create appropriate object
  │
  └── NO → keep in Inbox
```

Prefer leaving an item temporarily unorganized over making a wrong destructive routing decision.

# 25. Organization Model

Do **not** use a rigid folder tree as the primary model. One item can belong in several contexts.

Example:

```text
"Buy Models by Mark Manson"
```

This relates to:

```text
Shopping
Books
Reading
Tasks
```

Instead organize using:

1. item type
2. collections
3. entities
4. tags / attributes
5. lifecycle
6. saved views

The UI can still look folder-like, but many folders should actually be queries/views.

# 26. Predefined Item Types

Keep hardcoded types small:

```text
note
task
reminder
list
reference
project
entity
```

These are application mechanics, not a taxonomy of the user's life.

Do not create a core database type for every possible concept such as restaurant, book, movie, cafe, research paper, trek, recipe or company.

# 27. Generic Entities

Use a generic entity abstraction.

```json
{
  "type": "entity",
  "entity_type": "restaurant",
  "name": "Comal"
}
```

```json
{
  "type": "entity",
  "entity_type": "book",
  "name": "Designing Data-Intensive Applications"
}
```

```json
{
  "type": "entity",
  "entity_type": "research_paper",
  "name": "Darwin Gödel Machine"
}
```

This lets new categories emerge without schema migrations.

# 28. Entities vs Notes

Entities represent **things**. Notes represent **knowledge or observations about things**.

```text
BOOK ENTITY
Designing Data-Intensive Applications

    ├── Chapter 3 note
    ├── Chapter 5 note
    ├── quote
    └── related idea
```

```text
RESTAURANT ENTITY
Comal

    ├── visit note
    ├── dishes liked
    ├── recommendation source
    └── future revisit reminder
```

```text
PROJECT ENTITY
Amnesiarch

    ├── architecture note
    ├── tasks
    ├── screenshots
    ├── decisions
    └── ideas
```

Useful mental model:

```text
Collection
    ↓
Entity
    ↓
Items
```

not:

```text
folder
  folder
    folder
      file.md
```

# 29. Collections

Collections are broad, stable areas the user can browse. Keep them few.

Possible defaults:

```text
Personal
Work
Projects
Reading
Fitness
Food
Travel
Ideas
```

The agent should **not casually create new top-level collections**. Otherwise organization degenerates into duplicate buckets such as Books, Reading, Book Notes, Learning, Resources, etc.

A new top-level collection should require explicit user instruction or strong repeated evidence that it is useful.

# 30. Tags and Attributes

Tags are flexible and cheap to create:

```text
#grocery
#shopping
#bangalore
#restaurants
#cafes
#system-design
#books
#to-buy
#ai
#running
```

Attributes hold structured data.

Restaurant example:

```text
entity_type: restaurant
city: Bengaluru
status: visited
rating: 4.5
```

Book example:

```text
entity_type: book
status: reading
author: Martin Kleppmann
```

Task example:

```text
status: open
due_at: 2026-09-07T10:00:00
priority: normal
```

# 31. Saved Views Instead of Physical Folders

The sidebar can still feel familiar:

```text
HOME

Inbox
Today

Personal
  Tasks
  Reminders
  Shopping
  Grocery

Reading
  To Read
  Reading
  Finished
  Book Notes

Food
  Restaurants
  Want to Try
  Favourites

Projects
  Amnesiarch
  Work

Notes
  System Design
  AI
  Random Ideas
```

Internally these can be saved queries.

```text
Shopping
=
type IN [task, list]
AND tags CONTAINS shopping
AND status != done
```

```text
Book Notes
=
type = note
AND source = offline_book
```

```text
Restaurants to Try
=
type = entity
AND entity_type = restaurant
AND status = want_to_try
```

This gives folder-like simplicity without a rigid tree.

# 32. Predefined vs Emergent Structure

Amnesiarch should predefine **system mechanics**, not the user's life taxonomy.

Predefined by Amnesiarch:

```text
Item types
Basic lifecycle semantics
Basic statuses
Inbox
Today
Recent
Tasks
Reminders
Search
A small number of stable collections
```

Emerges from user data:

```text
Tags
Topics
People
Books
Restaurants
Cafes
Projects
Places
Custom lists
Research papers
Movies
Companies
Relationships
Custom entity types
```

Core principle:

> **Predefine the mechanics, not the user's life taxonomy.**

# 33. Classification Examples

User:

```text
"I need to buy milk, eggs and bananas tomorrow."
```

Agent:

```text
intent: update/create grocery list
type: list / task
collection: Personal
tags: [grocery]
due: tomorrow
lifecycle: ephemeral
```

User:

```text
"Models by Mark Manson looks interesting. Add it to books."
```

Agent:

```text
type: entity
entity_type: book
status: want_to_read
collection: Reading
```

User:

```text
"Comal was great, especially the tacos."
```

Agent:

```text
type: entity
entity_type: restaurant
collection: Food
status: visited
location: Bengaluru
```

with a linked note containing the observation about the tacos.

User:

```text
"This chapter explains look-aside caches really well."
```

Agent:

```text
type: note
source: offline_book
tags: [system-design, caching]
linked_entity: <current book>
```

# 34. Persistent Memory vs Operational State

Not everything captured should remain permanently active.

```text
CONTENT

├── Memory
│   └── intended to remain useful over time
│
└── Operational
    └── useful until a time, completion, or condition
```

Persistent examples:

```text
system design notes
book notes
restaurant recommendations
project decisions
ideas
people
research notes
travel knowledge
```

Operational examples:

```text
buy milk tomorrow
daily reminder
grocery list
shopping task
call dentist at 4 PM
temporary packing checklist
deadline
```

The agent should distinguish these at capture time.

# 35. Lifecycle Model

Predefine lifecycle semantics because this is system behavior.

Recommended values:

```text
persistent
ephemeral
recurring
```

Operational status can be separate:

```text
active
completed
expired
archived
```

Examples:

```text
type: note
lifecycle: persistent
```

```text
type: task
lifecycle: ephemeral
status: active
due_at: tomorrow
```

```text
type: reminder
lifecycle: recurring
status: active
recurrence: daily
```

# 36. Invalidation and Expiration

Some information should automatically stop appearing in active surfaces.

Example:

```text
"Remind me to carry my charger tomorrow."
```

Representation:

```text
type: reminder
lifecycle: ephemeral
due_at: 2026-09-07T09:00:00
```

After completion:

```text
status: completed
```

If it becomes irrelevant without completion:

```text
status: expired
```

It should no longer appear in Today, active reminders, or normal semantic memory search unless history is explicitly requested.

# 37. Recurring Reminders

Do not create thousands of permanent objects for recurring reminders.

Example:

```text
"Take creatine every day at 9 AM."
```

Store one recurring definition:

```text
content: Take creatine
lifecycle: recurring
recurrence: daily
time: 09:00
status: active
```

Occurrences can be temporary operational records if needed. The persistent object is the recurring rule, not every daily instance.

# 38. Grocery and Shopping Lists

A grocery list should behave as operational state rather than long-term semantic memory.

```text
Grocery List

- eggs
- milk
- bananas
```

Once all items are checked:

```text
active list disappears
```

Optionally retain a lightweight historical record such as:

```text
"Grocery list completed Sep 7"
```

Old grocery items should normally be excluded from semantic search to avoid noise.

# 39. Search Should Respect Lifecycle

Different questions should search different data classes by default.

```text
"What do I need to do today?"
→ active tasks + reminders + due operational items
```

```text
"What did I buy last week?"
→ archived operational history
```

```text
"What do I know about caching?"
→ persistent memory
```

Expired operational state should not pollute ordinary long-term retrieval.

# 40. Suggested Expanded Data Model

The original `captures`, `notes`, and `note_sources` model remains valid.

Possible richer model:

```text
captures
notes
entities
tasks
reminders
lists
list_items
note_sources
relationships
collections
tags
item_tags
```

Do not necessarily build every table immediately. A generic v0 can use a unified interpreted-object table.

```sql
items

id
item_type
title
content_md
collection_id
lifecycle
status
created_at
updated_at
expires_at
due_at
metadata JSONB
```

A compact initial model could therefore be:

```text
captures       → immutable/raw input
items          → interpreted user objects
relationships  → links between objects
```

Specialized tables can be added only when behavior actually requires them.

# 41. Relationships

Avoid forcing relationships into folders. Use explicit links.

Examples:

```text
note → about → DDIA
task → related_to → Amnesiarch
restaurant_note → about → Comal
screenshot → source_for → Amnesiarch Architecture
book → related_to → System Design
```

Generic representation:

```text
relationships

source_id
relation_type
target_id
metadata
```

Potential relation types:

```text
about
part_of
related_to
source_for
derived_from
mentions
supports
contradicts
```

Do not overbuild a full graph system in v0.

# 42. Undo and Provenance for Agentic Writes

Because an agent can autonomously modify memory, every agentic write should be reversible.

```text
action_log

id
capture_id
agent_action
target_id
before_state
after_state
created_at
```

Desired UX:

```text
Added to "Amnesiarch Architecture"
[View] [Undo]
```

General policy:

```text
high confidence → perform + View/Undo
low confidence  → Inbox or ask for routing
destructive     → require confirmation
```

# 43. Voice as the Personal Command Line

Voice should function almost like a command line for the personal system.

Examples:

```text
"Remember this."
"Add this to my running notes."
"Models by Mark Manson looks interesting, add it to books."
"I need eggs tomorrow."
"Comal was great, save it under restaurants."
"Remind me every morning to take creatine."
"What was that startup idea I had about Git?"
```

The user should not need to manually navigate folders before capturing.

# 44. Revised Product Mental Model

Earlier mental model:

```text
AI-powered notes system
```

Better mental model:

> **A personal agent with persistent memory and operational state.**

```text
                       USER

              voice / text / share
                       │
                       ▼
                    CAPTURE
                       │
              raw source persisted
                       │
                       ▼
                 MEMORY AGENT
                       │
       ┌───────────────┼────────────────┐
       ▼               ▼                ▼
    Memory         Operational        Search
    notes          tasks/lists       retrieval
    entities       reminders
    references
       │               │
       └───────────────┼────────────────┘
                       ▼
                  Canonical Store
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
         UI           MCP         Export
```

# 45. Revised Design Principles

1. **Persist before reasoning.** Raw capture is stored before agentic processing.
2. **Agent reasons, backend executes.** The LLM chooses actions; deterministic tools perform them.
3. **Do not force a folder.** Use metadata, entities, relationships and views.
4. **Predefine mechanics, not taxonomy.** User-specific structure should emerge.
5. **Know what should stop mattering.** Support expiry, completion, invalidation and archival.
6. **Operational state is not long-term memory.** Tasks/reminders/groceries should not pollute semantic recall forever.
7. **Stable collections, flexible tags.** Top-level organization changes slowly; fine-grained organization can evolve rapidly.
8. **Entity-centric where useful.** Books, restaurants, people, projects, places and papers should be reusable things with items attached.
9. **Reversible agent actions.** Autonomous writes require provenance and Undo.

# 46. Updated v0 Recommendation

```text
INPUTS
- voice
- text
- screenshot
- link
- MCP

CORE
- immutable raw capture
- memory agent
- deterministic tools
- generic items/entities
- lifecycle semantics
- provenance / undo

OBJECTS
- notes
- tasks
- reminders
- lists
- references
- projects
- entities

ORGANIZATION
- small stable collections
- flexible tags
- generic entity types
- relationships
- saved views instead of rigid folders

LIFECYCLE
- persistent
- ephemeral
- recurring

SURFACES
- Capture
- Inbox
- Today
- Search
- Notes / Browse

BACKEND
- FastAPI
- Supabase Postgres
- Supabase Storage
- MCP endpoint/server

PORTABILITY
- Markdown + JSON + attachments export
```

# 47. Updated One-Sentence Product Definition

> **Amnesiarch is a voice-first personal agent that captures raw thoughts and references, interprets them into persistent memory or temporary operational state, organizes them through entities, metadata and views rather than rigid folders, and exposes the resulting personal context through its own UI and MCP while preserving provenance, lifecycle and portability.**
