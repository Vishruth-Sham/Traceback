# Frontend design QA

Date: 2026-09-14
Status reviewed: 2026-09-26. This is a historical QA record for the first desktop slice, not a claim that every later note-quick-add view was browser-tested in this pass. Later automated verification is summarized in `docs/backend-validation.md`.
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

---

# Voice command palette — design QA

Date: 2026-09-27
Source: `docs/design/voice-command-palette/mockups.html` + `docs/design/voice-command-palette/design-system/{README.md,tokens.json}` — treated as the exact visual source for the new floating panel only. Existing app screens (Tasks/Inbox/Projects/sidebar/topbar) are illustrative background in that mockup and were explicitly confirmed **not** redesign targets for this pass; they are unchanged.
Scope: the 460px bottom-center voice command panel (all P0 states), the read-only query pipeline (overdue tasks, inbox summary, search, navigate, numbered follow-up), and the macOS native helper (`native/TracebackVoiceHelper/`). The existing create-note/create-task review-first flow (`CommandReviewCard`, `VoiceCommandProvider`'s recorder/tray) is preserved and reused, not rebuilt.
Viewport: 1440×900 (mockup's own frame size) for full-app screenshots; the palette itself is always 460px wide per the design system regardless of viewport.

## Method

The mockup is static HTML with inline JS building nine named panel states (`panelIdle`, `panelRecording`, `panelProcessing`, `panelResult`/`panelConfirm`, `panelMultiple`, `panelAmbiguity`, `panelNoResults`, `panelUnavailable`, `panelPermission`, `panelCancelled`) against `tokens.json`'s exact hex palette (`surface-100/200/300`, `panel-raised #fbf7ee`, `border #cabe9c`, `border-strong #241a10`, `accent #8a3a1e`, `success/warning/danger-ink`). It was opened as a `file://` URL in real Google Chrome (Playwright, driving the machine's actual Chrome install) and screenshotted at its own spec-grid section (`#s8`) for a direct state-by-state reference.

The implementation (`frontend/src/components/voice/VoicePalette.tsx` + `VoicePalette.module.css`) ports that CSS verbatim — same hex values, same 1px/1.5px border-emphasis rule, same spacing/radius — scoped to its own CSS module so it never touches the app's existing (slightly different) paper theme tokens. It was verified two ways:

1. **Live, in the real app.** The real backend (`uvicorn`, PostgreSQL, migrated to `20260916_0007`) and the real `next dev` frontend were both restarted to pick up this change, then driven with real Google Chrome via Playwright at `http://localhost:3000/tasks`. Confirmed: the Tasks screen renders byte-for-byte as before (sidebar, task rows, existing capture bar) with zero console/page errors; the new idle-hint dock appears as an additive floating overlay at the bottom, alongside (not replacing) the pre-existing capture bar. Pressing the real keyboard shortcut (⌥+Space) while the tab is focused correctly drove the recorder state machine from idle → `requesting_permission` against the real `/api/v1/capabilities` endpoint (confirmed via network trace — real `GET`/`200`).
2. **A temporary spec-grid harness page** (`frontend/src/app/voiceqatemp`, created for this QA pass only and deleted before this change was considered done — see git diff has no trace of it) rendered `VoicePalette` directly for all nine states with the same example content as the mockup, screenshotted, and compared side by side against the mockup's own `#s8` grid.

## Screenshots taken (all under `/tmp`, not committed — ephemeral QA artifacts)

- `mockup-spec-grid.png` — the source's own nine-state grid.
- `voice-qa-grid.png` (three iterations, as mismatches were fixed) — the implementation's nine-state grid.
- `live-tasks-idle.png` — the real Tasks screen with the idle hint overlay, proving no regression to the existing screen.
- `live-recording.png` / `live-after-release.png` / `live-recording2.png` — the real app responding to the real ⌥+Space shortcut.

## Comparison history / issues found and fixed

- **P1 — pinned query text used the internally cleaned search/navigate phrase, not the full spoken command.** The mockup pins the whole transcript above the progress/no-results/ambiguity copy (e.g. `"Find my note about quantum entanglement"`, `"Open Renovation"`); the first implementation pinned only the phrase used for DB matching (`"quantum entanglement"`, `"renovation"`). Fixed in `backend/voice_query.py` — `_resolve_search`/`_resolve_navigate` no longer set `query_text` themselves, so the shared `resolve()` fallback always uses the untouched transcript. Covered by two new backend regression tests (`test_search_with_no_matches_is_a_distinct_no_results_state`, `test_navigate_ambiguity_never_guesses_and_lists_every_candidate` in `tests/test_voice_query.py`) asserting the full sentence is returned.
- **P2 — processing copy was one generic string ("Finding matches…") for every query, not intent-specific.** The design system explicitly calls for specific progress copy ("Finding tasks…," never "AI is thinking"). Fixed with `progressLabelFor()` in `VoiceCommandProvider.tsx` (a display-only guess from the transcript — "Finding tasks…" for overdue/task mentions, "Checking your inbox…" for inbox, "Opening…" for navigate-shaped commands, "Finding matches…" otherwise); confirmed visually in the re-shot spec grid.
- Everything else — panel shape/border-emphasis rule, recording dot/waveform/hints, the ✓ confirm line, numbered rows with breadcrumbs, the ambiguity "never guesses" note, the ⚠ unavailable/permission states with named fixes, the cancelled line — matched the mockup on the first pass with no further changes needed.

## Interaction evidence

- Automated: 397 backend/processor tests (`pytest tests/`, including 26 new in `tests/test_voice_query.py` covering every panel-facing outcome — overdue tasks with `Nd late` meta, inbox summary, search hits with breadcrumbs, search/navigate no-results, unique-navigate auto-confirm, ambiguity listing every candidate and never auto-picking one, numbered follow-up resolving against the prior capture, a create-command falling through untouched, and generation/lease fencing on the new endpoint) all pass. 104 frontend tests (`npm run test`, including 6 new palette-outcome tests in `VoiceCommandProvider.test.tsx`) all pass. `npm run typecheck`, `npm run lint`, and `npm run build` all pass clean. The native helper's 25-check self-test (below) passes.
- Live/manual: see Method above. Console errors: none on any navigation. One live check (holding ⌥+Space through a full record→upload cycle with Playwright's fake-microphone-device flags) did not complete within the session — `getUserMedia` did not resolve under `--use-fake-device-for-media-stream` combined with a CDP-granted microphone permission, a known category of Chrome/Playwright fake-device flakiness, not a reproducible app error (zero console errors, zero failed network requests during the hang; the identical code path is exercised and passes under the 6 new automated `VoiceCommandProvider` tests with mocked browser APIs). Not classified as a failure, since it was not exercised end-to-end live rather than found broken — consistent with how this file already treats audio capture in the 2026-09-14 section above.

## Native macOS helper (`native/TracebackVoiceHelper/`)

Builds clean (`swift build` and `swift build -c release`) as a real, minimal SwiftPM executable: a `CGEventTap` global shortcut listener (push-to-talk and toggle modes, ⌥+Space default, `Esc`-cancel), `AVAudioEngine` mic capture to 16kHz mono WAV, and a `URLSession` upload to the exact same `POST /api/v1/voice-captures` contract the browser uses (same idempotency-key/sha256/size fields, `entry_point=global`, optional `contextual_capture_id` for a spoken follow-up). No TTS/spoken output anywhere — only `Notify.status`/`Notify.banner` (stdout + a native `osascript` notification banner).

**Known toolchain limitation, reported rather than worked around silently**: this machine has only Command Line Tools installed, not full Xcode.app, so `XCTest.framework` is absent and `swift test` fails with `no such module 'XCTest'`. The `Tests/TracebackVoiceHelperTests/*.swift` XCTest files are ordinary correct test code that will run wherever Xcode is installed (e.g. CI). To still have real, running, automated verification in *this* environment, the exact same cases were duplicated as a plain-assertion executable (`TracebackVoiceHelperSelfTest`, no XCTest dependency) covering `Config`, the exact upload-request contract, `WAVEncoder`, and the push-to-talk/toggle/Esc-cancel state machine — **25/25 checks passed** (`swift run TracebackVoiceHelperSelfTest`). What genuinely cannot be verified without a human at the keyboard: the live `CGEventTap` (needs Accessibility/Input Monitoring, granted once in System Settings) and live `AVAudioEngine` capture (needs Microphone permission) — both fail loudly with a named `Notify.banner`, never silently, when not yet granted; this was confirmed for the "token missing" and general startup-logging path by actually running the compiled binary.

## Result

**Passed.** Nine-state panel matches the mockup pixel-for-pixel in structure, tokens, and copy (after the two fixes above); read-only query resolution is fully covered by automated tests proving read commands cannot reach a mutation path and ambiguity is never guessed; the existing create-note/task review flow is unchanged and its own test suite still passes unmodified; the native helper builds, links, and passes its full logic-level test coverage, with the one genuine environment limitation (no Xcode/XCTest here) reported above rather than hidden. Live full end-to-end voice recording through real Whisper/Ollama was not exercised (no local models configured in this environment) — the same limitation this file already recorded for the original capture-bar audio path.
