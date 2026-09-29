# Traceback — Voice Command Palette

A voice-first interaction system for Traceback, a local-first desktop app for notes, tasks, projects, folders, categories, inbox captures and search. Voice recording, transcription (Whisper) and command interpretation (Ollama) run entirely on-device — nothing leaves the Mac.

This system covers **P0: voice search, navigation and read-only queries.** P0 never modifies data — it searches, filters, summarizes, opens or navigates. Write commands (create, edit, complete, archive, undo) are designed for, but not shipped, in this release; see *Future-proofing* below.

## The interaction model

Voice behaves like a **command palette, not a chatbot.**

There is no chat page, no assistant avatar, no message bubbles, no conversational history, and no separate "AI workspace." Instead, one compact floating panel — the **voice command panel** — appears transiently over whichever Traceback screen is already open, does its job, and disappears. The screen underneath is always the canonical, full view; the panel is a summary layered on top of it, never a second version of the app.

## Activation

A configurable, system-wide macOS shortcut (default placeholder: **⌥ Option + Space**) starts a voice command, whether Traceback is focused or the user is in another Mac app.

- **Primary mode** — hold to record, release to send, `Esc` to cancel.
- **Accessibility mode** — press once to start, press again to stop.

If Traceback isn't focused when the shortcut fires, it is **never pulled to the foreground unexpectedly.** Simple results and clarifications surface as a native macOS notification instead; clicking it opens Traceback directly at the relevant result.

## The panel: one component, nine states

Every voice interaction moves through the same 460px-wide floating panel, docked bottom-center, 32px from the edge of the content area. Only its content and border emphasis change:

1. **Idle / ready** — a quiet resting hint, 1px border.
2. **Recording** — pulsing dot, elapsed time, waveform, release/cancel hints. 1.5px border.
3. **Processing** — the transcribed query pinned above specific progress copy ("Finding tasks…," never "AI is thinking"). 1.5px border.
4. **Successful result** — a compact list (search/filter) or a one-line confirmation (navigation), 1px border.
5. **Multiple matches** — numbered rows with full breadcrumbs; voice or click to pick one.
6. **Ambiguity / clarification** — same shape as multiple matches, used specifically when names collide; Traceback never guesses.
7. **No results** — a plain, specific dead-end with a suggested rephrase.
8. **Backend / processor unavailable** — warning glyph + red-toned text, a named fix, 1px border.
9. **Microphone permission missing** — same treatment as unavailable, with a path to System Settings.
10. **Cancelled** — a single neutral line confirming nothing was sent.

See the **VoicePanel / State Specification** card for all nine side by side, and each **Screens** card for a full 1440×900 view of the panel over a real Traceback screen.

## Read-only actions happen immediately

Navigation ("Open the DSA Learning project") and unambiguous filters ("Show my overdue tasks") execute the moment the command resolves — no confirmation step, no review screen. Confirmation exists only for write actions in later releases, never for P0 reads.

## Ambiguity is never guessed

Whenever two items could match — same project name, same note title — Traceback shows every candidate with disambiguating context (full breadcrumb, item type, last-modified date when needed) and waits for the user to choose, by voice ("the first one") or by click. It never silently picks the most likely one.

## Outside Traceback

While another app is focused, results and clarifications arrive as a native macOS notification instead of stealing focus. A result notification names the count and the command; an ambiguity notification says a decision is needed and sends the user to the clarification panel on click — it never names a guessed item.

## Future-proofing (not shipped in P0)

The same panel is designed to grow into multi-step write commands without a new surface:

- Creating, editing, moving, completing/reopening, archiving/restoring items.
- Multiple operations proposed as one **voice plan** ("VOICE PLAN · 3 ACTIONS") with **Accept all · Edit plan · Cancel**.
- Voice corrections, and an **Undo** affordance after any applied action.
- Destructive actions always pass through an explicit confirmation card — never auto-executed.

Future write states extend the panel's existing shape (460px dock, same border-emphasis rule, same type scale) rather than introducing a review modal, a chat surface, or a second navigation model.

## Visual language

Traceback's existing character — restrained, warm, paper-like — is preserved, not replaced, by voice:

- Beige/cream surfaces, dark brown/black ink, one warm accent used sparingly (recording, active nav).
- Monospace type throughout; thin 1px hairlines at rest, a 1.5px outline only while the panel is actively listening or thinking.
- No gradients, no glassmorphism, no cartoon assistant, no chat-bubble styling anywhere in the system.
- Status is never color-only: "late," "✓," and a warning glyph always carry the meaning color reinforces.
- Motion is minimal and respects `prefers-reduced-motion` (the recording pulse and spinner both degrade to a much slower or static state, never disappear).

---
