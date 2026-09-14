# Frontend design QA

Date: 2026-09-14
Scope: first implemented slice of the Traceback desktop UI (`frontend/`), reviewed against the newer reference export `initial UI views/Modern minimal UI design/Traceback Main Page (standalone).html` (a Claude Design canvas export) and `docs/ui-plan.md`.

## Method

The reference export's HTML contains compressed inline JS blobs and is not readable as plain markup — it must be rendered. It was opened directly as a `file://` URL in headless Chromium (Playwright, installed as a dev-only tool for this pass, not a runtime dependency) and screenshotted. It turned out to be a canvas of **9 stacked artboards** ("2a — capture, ink & paper" through "10a — Today, a shortcut across areas"), each screenshotted individually at full resolution: Today, Inbox, Skills, Note preview/edit, Learning index, a project detail, Projects, Notes, and a capture/conversation view.

That rendering is the actual visual target: a warm cream/parchment background (not white), serif display type for headings and content titles, monospace for all UI chrome — nav, labels, tags, meta, buttons, breadcrumbs — square (not rounded) checkboxes, thin hairline dividers, bordered rectangular tags/pills/buttons instead of filled pill shapes, a two-button bordered segmented toggle instead of a grouped pill switch, boxed 3-column stat rows, and a bordered card grid for Projects. The implementation uses macOS/system serif and monospace stacks so a local production build never depends on downloading Google fonts; this preserves the direction while making startup reproducible offline.

Visual verification of the rebuilt app used the same headless Chromium approach driving the real `next dev` server against the real local FastAPI backend and PostgreSQL database, at a 1440×900 desktop viewport. Console/page errors were captured on every navigation.

## Verified flows

- **Navigation**: sidebar routes to Inbox, Tasks, all six fixed categories (Health & Food, Personal Growth, Books, Learning, Projects, Other), Archive, Skills; Search reachable from the sidebar. Tasks is the landing page (`/` redirects to `/tasks`).
- **Tasks**: add an undated task, open its detail panel, set a past due date, confirm the "Overdue" badge and red "Overdue · Jan 1" label render, confirm the row moves into the "Overdue" section on close. Marked complete with an Undo toast; task left the Open list and the toast's Undo path was exercised.
- **Capture**: typed capture saved from the bottom bar, confirmed toast "Saved — awaiting processing," confirmed the capture appears in Inbox as an unsorted card with source type, timestamp, and processing state.
- **Inbox classification**: "+ new note" on a capture card creates a real note, links it as capture provenance (`interpretations` with an `append` op), and the capture disappears from the unsorted list per the backend's resolved-capture semantics. "Move to" on an unclassified item moved it into Health & Food and it left the unclassified list.
- **Projects**: created a project, opened its detail page, added a note inside project context — the note was created and linked with a `part_of` relation automatically, and appeared in the project's linked-items list immediately.
- **Archive/restore**: an archived project appeared correctly in Archive → Items with Restore/Delete actions; clicking Restore returned it to Projects and the Archive list correctly emptied.
- **Layout alignment**: the floating capture bar is bounded to the content pane (`left: 240px` = sidebar width, not the full window), and every page content column shares the same `max-w-[760px] px-10` container, so the capture bar's left edge lines up exactly with the page content's left edge at every width — this was reported as broken (bar centered on the whole window, content centered only in the pane to its right) and is now fixed.
- **Zero console/page errors** across all seven routes and all of the above interactions (a dev-mode Turbopack HMR websocket warning is unrelated to the app and absent from a production build).

## Product-direction correction applied mid-review

The user also pointed out that tasks must only be creatable from the Tasks screen. `QuickAdd` (used on category pages and inside a project) previously offered a note/task type selector; it now always creates a note, with no type picker anywhere outside Tasks. `CaptureCard`'s "Create task" action was removed for the same reason — Inbox captures can only be organized into a note; linking an existing task to a project happens from the task's own detail panel (its Links section can search for and link to a project).

## Not exercised in this pass

- Audio capture (MediaRecorder → asset upload → capture) is implemented against the real endpoints but not exercised here: a headless browser has no real microphone, and this environment has no local Whisper/Ollama processor running, so the resulting capture would sit at "Saved — awaiting processing" indefinitely either way. The typed-capture path, which is the required first slice per `docs/ui-plan.md`, was fully exercised.
- Permanent deletion and multi-client version-conflict banners were implemented and code-reviewed against the API contract (`docs/backend-api.md`) but not driven live: permanent deletion is correctly irreversible, and an attempt to script cleanup of QA-created test records via the API was itself blocked by the environment's own destructive-action guard. A few such demo records remain in the local dev database; they can be archived/deleted by hand from the UI whenever wanted.
- Narrow-desktop / browser-zoom edge cases were not screenshotted separately; the layout uses a `min-w-[860px]` shell with internal scrolling, which is the documented desktop-only behavior, but no dedicated screenshot exists below 1440px.

## Issues found and resolved during this pass

- **P0 — visual direction did not match the reference at all.** The first implementation judged the mockup from a low-resolution thumbnail instead of rendering it, and shipped a generic light/rounded SaaS look. Fixed by rendering all 9 real artboards and rebuilding the color tokens, typography (serif + monospace), checkbox/tag/button shapes, and per-page layout to match. See Method above.
- **P0 — capture bar misaligned with page content.** The bar was centered on the full browser window; page content is centered only within the pane right of the fixed sidebar. Fixed by bounding the bar to `left-[240px] right-0` and standardizing every page's content container to the same max-width/padding as the bar's inner container.
- **P1 — product-rule violation: tasks could be created outside Tasks.** `QuickAdd` offered a task option on category/project pages. Fixed by removing the type picker; those surfaces create notes only.
- **P0 — dev-only false negative, not a shipped bug**: accessing the Next dev server via `http://127.0.0.1:3000` (rather than `http://localhost:3000`) silently blocked every client-side fetch to `/api/v1/*` with no console error, because Next 16's dev-only cross-origin protection also affects this Turbopack dev session's asset pipeline for non-`localhost` hosts. Fixed by standardizing on `http://localhost:3000` for local development; documented in `docs/local-development.md`. Does not reproduce in a production build.

No other P0/P1/P2 issues were found in this pass.

## Result

**Passed** for the implemented slice (navigation, Tasks, Inbox classification, category item lists, Projects/membership, typed capture, detail panel editing/move/link/complete/archive affordances), now evaluated against the reference's *actual rendered* visual direction (not a thumbnail) and the current product decisions, including the tasks-only-in-Tasks rule. Audio-capture and permanent-deletion flows are implemented but unverified live, as noted above; they are not classified as failing, since they were not exercised rather than found broken.
