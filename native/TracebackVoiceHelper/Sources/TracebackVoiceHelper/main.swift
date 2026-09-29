import Foundation
import TracebackVoiceHelperCore

/// Traceback's macOS voice command helper: a minimal, no-UI, no-TTS background process that
/// turns the configured global shortcut into the exact same `POST /api/v1/voice-captures`
/// upload the in-app recorder makes, so system-wide voice commands land in the same
/// capture-first, generation/lease-fenced pipeline (`backend/voice.py`, `processor/voice.py`)
/// regardless of which app is focused. It never brings Traceback to the foreground itself; the
/// backend/frontend already handle "show a result/clarification as a notification" on their side
/// via the resolved capture. This process never speaks (no TTS) and never types on the user's
/// behalf — its only outputs are the upload, a `Notify.banner`, and status lines on stdout.

let config: Config
do {
    config = try Config.load(from: ProcessInfo.processInfo.environment)
} catch {
    Notify.status("blocked: \(error)")
    exit(1)
}

Notify.status("starting (mode: \(config.shortcutMode.rawValue), backend: \(config.apiBaseURL.absoluteString))")

let micState = Permissions.microphoneState()
if micState == .denied {
    Notify.banner(title: "Microphone access needed", body: "Grant microphone access in System Settings \u{2192} Privacy & Security, then restart the helper.")
    exit(1)
}
if micState == .notDetermined {
    let group = DispatchGroup()
    group.enter()
    var granted = false
    Permissions.requestMicrophone { ok in
        granted = ok
        group.leave()
    }
    group.wait()
    if !granted {
        Notify.banner(title: "Microphone access needed", body: "Grant microphone access in System Settings \u{2192} Privacy & Security, then restart the helper.")
        exit(1)
    }
}

let recorder = Recorder()
var machine = HotkeyStateMachine(mode: config.shortcutMode)
var pendingContextCaptureID: String?

func startRecording() {
    do {
        try recorder.start()
        Notify.status("recording\u{2026} (release/press again to send, Esc to cancel)")
    } catch {
        Notify.banner(title: "Voice processing unavailable", body: "Could not start the microphone: \(error.localizedDescription)")
    }
}

func stopAndSend() {
    guard let (wav, durationMs) = recorder.stop() else {
        Notify.status("too short; nothing was sent")
        return
    }
    let request = VoiceCaptureRequest.build(
        config: config,
        audio: wav,
        capturedAt: Date(),
        sourceTimezone: TimeZone.current.identifier,
        durationMs: durationMs,
        idempotencyKey: UUID().uuidString,
        contextualCaptureID: pendingContextCaptureID
    )
    Notify.status("uploading\u{2026}")
    BackendClient.upload(request) { result in
        switch result {
        case .created(let captureID):
            Notify.status("saved (capture \(captureID ?? "?")) \u{2014} transcribing")
            pendingContextCaptureID = nil
        case .httpError(let status, let body):
            Notify.banner(title: "Voice processing unavailable", body: "The backend rejected the recording (HTTP \(status)). \(body.prefix(200))")
        case .transportError(let message):
            Notify.banner(title: "Voice processing unavailable", body: "The local processor isn't reachable: \(message)")
        }
    }
}

func cancelRecording() {
    recorder.cancel()
    Notify.status("cancelled \u{2014} nothing was sent")
}

let listener = GlobalHotkeyListener(config: config) { event in
    switch machine.handle(event) {
    case .start: startRecording()
    case .stop: stopAndSend()
    case .cancel: cancelRecording()
    case .none: break
    }
}

do {
    try listener.start()
    Notify.status("listening for the shortcut (Option+Space by default). Ctrl-C to quit.")
} catch {
    Notify.banner(title: "Voice shortcut unavailable", body: "\(error)")
    exit(1)
}

CFRunLoopRun()
