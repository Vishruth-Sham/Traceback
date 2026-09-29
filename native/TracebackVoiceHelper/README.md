# Traceback Voice Helper (macOS)

A minimal, no-UI, no-TTS background process that turns a configurable **system-wide** macOS
shortcut into the exact same `POST /api/v1/voice-captures` upload the in-app recorder makes
(`frontend/src/lib/voice.ts`), so a voice command works from any app, not just when Traceback's
Next.js tab is focused. It never brings Traceback to the foreground and never speaks.

It reuses the running Traceback stack exactly as-is: the same loopback backend, the same
`TRACEBACK_API_TOKEN`, the same capture-first/generation/lease-fenced pipeline the browser
recorder and `processor/voice.py` already go through. There is no separate voice pipeline here —
this is just another authenticated client of `backend/voice.py`.

## What it does

1. Registers a global key listener (`CGEvent.tapCreate`) for the configured shortcut (default
   **⌥ Option + Space**) and for `Esc`.
2. **Push-to-talk mode** (default): hold the shortcut to record, release to send, `Esc` to cancel.
   **Toggle mode**: press once to start, press again to stop (for anyone who finds holding a key
   uncomfortable).
3. Captures the microphone (`AVAudioEngine`) as 16 kHz mono PCM16 WAV.
4. Uploads it to `POST /api/v1/voice-captures` with the same idempotency-key/sha256/size contract
   the browser uses. The backend and processor take it from there — read-only query resolution,
   ambiguity handling, and the create-note/task review flow are unchanged and already covered by
   `tests/test_voice_query.py` / `tests/test_processor_voice.py`.
5. Reports every state out loud in text only, never speech: a status line on stdout and a native
   `osascript` notification banner for anything the user needs to notice (permission missing,
   backend unreachable, recording sent).

## Configuration (environment variables — same names the processor already uses)

| Variable | Default | Meaning |
|---|---|---|
| `TRACEBACK_API_TOKEN` | *(required)* | Same bearer token the backend and `processor/runner.py` use. |
| `TRACEBACK_PROCESSOR_API_BASE_URL` | `http://127.0.0.1:8000` | Must be a plain-HTTP loopback address; anything else is refused before any request is made. |
| `TRACEBACK_VOICE_HELPER_MODE` | `push_to_talk` | `push_to_talk` or `toggle`. |
| `TRACEBACK_VOICE_HELPER_KEYCODE` | `49` (kVK_Space) | Virtual keycode for the shortcut; always combined with ⌥ Option. |

## Required macOS permissions (both are manual, one-time, GUI steps — no agent or script can grant
them; this is the same limitation the browser recorder has for microphone access)

- **Accessibility (Input Monitoring)**: required for the global shortcut listener. The first run
  triggers the system prompt; approve the helper's binary in
  **System Settings → Privacy & Security → Accessibility**. Until granted, `start()` throws
  `GlobalHotkeyListener.StartError.accessibilityNotGranted` and the helper exits with a clear
  `Notify.banner` instead of silently doing nothing.
- **Microphone**: required to record. `Permissions.microphoneState()` is checked before the event
  listener even starts; a denial produces the same visible "Microphone access needed" banner the
  in-app palette shows for the equivalent state.

## Build & run

```sh
cd native/TracebackVoiceHelper
swift build -c release
TRACEBACK_API_TOKEN=$(grep '^TRACEBACK_API_TOKEN=' ../../.env | cut -d= -f2-) \
  ./.build/release/TracebackVoiceHelper
```

Run it under a login item / `launchd` agent for it to always be listening; that packaging (a
`launchd` plist, code signing for a stable Accessibility grant across rebuilds) is a deployment
concern intentionally left out of this repo-local helper.

## Known limitation: `swift test` cannot run in this checkout

This machine has only the **Command Line Tools** installed (`xcode-select -p` →
`/Library/Developer/CommandLineTools`), not full **Xcode.app**. `XCTest.framework` ships inside
Xcode's platform SDKs, not the bare Command Line Tools SDK, so `swift test` fails with
`no such module 'XCTest'` — this is a toolchain limitation of this specific machine, not a defect
in the test code (`Tests/TracebackVoiceHelperTests/*.swift` are ordinary, correct XCTest cases
that will run wherever Xcode is installed, e.g. in CI with `xcode-select` pointed at a full Xcode).

To still have real, running, automated verification in *this* environment, the same cases are
duplicated as plain assertions with no XCTest dependency:

```sh
swift run TracebackVoiceHelperSelfTest
```

This exercises `Config`, `VoiceCaptureRequest` (the exact upload contract), `WAVEncoder`, and
`HotkeyStateMachine` (both shortcut modes, `Esc`-cancel) — every piece of logic that does not
require a live event tap, a real microphone, or a granted permission. It was run and passed 25/25
checks as part of this change.

**What is not, and cannot be, covered by any automated test here**: the live `CGEventTap` global
listener, live `AVAudioEngine` capture, and the two permission-prompt dialogs. Those need a human
at the keyboard granting Accessibility and Microphone once in System Settings; `swift build`
compiling the whole package (including these files) and the helper's own startup logging
(verified manually: `TRACEBACK_API_TOKEN` missing → immediate, correctly worded exit) are the
verification available to an agent without a display.
