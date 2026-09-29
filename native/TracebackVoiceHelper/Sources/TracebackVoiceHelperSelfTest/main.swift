import Foundation
import TracebackVoiceHelperCore

// This checkout only has Command Line Tools installed (no Xcode.app), and XCTest.framework is
// not present without full Xcode, so `swift test` cannot run here (see native/README.md
// "Known limitation"). This is a plain-assertion smoke test covering the same pure-logic cases
// as Tests/TracebackVoiceHelperTests so there is still real, running, automated verification in
// this environment; the XCTest files remain correct and will run wherever Xcode is installed.

var failures = 0

func check(_ name: String, _ condition: @autoclosure () -> Bool) {
    if condition() {
        print("ok   - \(name)")
    } else {
        print("FAIL - \(name)")
        failures += 1
    }
}

func expectThrows<T>(_ name: String, _ body: () throws -> T) {
    do {
        _ = try body()
        print("FAIL - \(name) (did not throw)")
        failures += 1
    } catch {
        print("ok   - \(name) (threw \(error))")
    }
}

// ---- Config ----
expectThrows("missing token is rejected") { try Config.load(from: [:]) }

do {
    let config = try Config.load(from: ["TRACEBACK_API_TOKEN": "secret"])
    check("defaults to the loopback backend", config.apiBaseURL.absoluteString == "http://127.0.0.1:8000")
    check("defaults to push-to-talk", config.shortcutMode == .pushToTalk)
    check("defaults to Space (kVK_Space=49)", config.shortcutKeyCode == 49)
} catch {
    check("default config loads", false)
}

expectThrows("a non-loopback base URL is rejected") {
    try Config.load(from: ["TRACEBACK_API_TOKEN": "x", "TRACEBACK_PROCESSOR_API_BASE_URL": "https://example.com"])
}

do {
    let config = try Config.load(from: ["TRACEBACK_API_TOKEN": "x", "TRACEBACK_VOICE_HELPER_MODE": "toggle"])
    check("honors an explicit toggle mode", config.shortcutMode == .toggle)
} catch {
    check("toggle mode config loads", false)
}

// ---- VoiceCaptureRequest ----
do {
    let config = try Config.load(from: ["TRACEBACK_API_TOKEN": "s3cret"])
    let audio = Data("fake-wav-bytes".utf8)
    let request = VoiceCaptureRequest.build(
        config: config, audio: audio, capturedAt: Date(timeIntervalSince1970: 1_790_000_000),
        sourceTimezone: "Asia/Kolkata", durationMs: 4200, idempotencyKey: "idem-123"
    )
    check("POSTs to /api/v1/voice-captures", request.httpMethod == "POST" && request.url?.path == "/api/v1/voice-captures")
    check("body is the raw audio bytes", request.httpBody == audio)
    check("Authorization is Bearer <token>", request.value(forHTTPHeaderField: "Authorization") == "Bearer s3cret")
    check("Content-Type is audio/wav", request.value(forHTTPHeaderField: "Content-Type") == "audio/wav")
    let query = Dictionary(uniqueKeysWithValues: URLComponents(url: request.url!, resolvingAgainstBaseURL: false)!.queryItems!.map { ($0.name, $0.value) })
    check("entry_point is global (never forces an in-app surface)", query["entry_point"] == "global")
    check("sha256 matches the audio bytes", query["sha256"] == VoiceCaptureRequest.sha256Hex(audio))
    check("no contextual_capture_id when none is given", query["contextual_capture_id"] == nil)

    let followup = VoiceCaptureRequest.build(
        config: config, audio: Data("x".utf8), capturedAt: Date(), sourceTimezone: "UTC",
        durationMs: 1, idempotencyKey: "k", contextualCaptureID: "cap-ambiguous"
    )
    let followupQuery = Dictionary(uniqueKeysWithValues: URLComponents(url: followup.url!, resolvingAgainstBaseURL: false)!.queryItems!.map { ($0.name, $0.value) })
    check("attaches follow-up context when given", followupQuery["contextual_capture_id"] == "cap-ambiguous")
} catch {
    check("VoiceCaptureRequest config loads", false)
}

check("sha256 of 'hello' is the known digest", VoiceCaptureRequest.sha256Hex(Data("hello".utf8)) == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824")

// ---- WAVEncoder ----
do {
    let wav = WAVEncoder.encode(pcm16: [1, -1, 100, -100])
    check("WAV starts with RIFF/WAVE", wav.prefix(4) == Data("RIFF".utf8) && wav[8..<12] == Data("WAVE".utf8))
    check("WAV header + 4 Int16 samples is 52 bytes", wav.count == 44 + 8)
    check("empty samples still produce a 44-byte header-only file", WAVEncoder.encode(pcm16: []).count == 44)
}

// ---- HotkeyStateMachine ----
do {
    var pushToTalk = HotkeyStateMachine(mode: .pushToTalk)
    check("push-to-talk: down starts", pushToTalk.handle(.shortcutDown) == .start)
    check("push-to-talk: key-repeat while recording is a no-op", pushToTalk.handle(.shortcutDown) == .none)
    check("push-to-talk: up stops", pushToTalk.handle(.shortcutUp) == .stop)

    var pushToTalkEscape = HotkeyStateMachine(mode: .pushToTalk)
    _ = pushToTalkEscape.handle(.shortcutDown)
    check("push-to-talk: Esc cancels while recording", pushToTalkEscape.handle(.escape) == .cancel)
    var pushToTalkIdle = HotkeyStateMachine(mode: .pushToTalk)
    check("push-to-talk: Esc while idle is a no-op", pushToTalkIdle.handle(.escape) == .none)

    var toggle = HotkeyStateMachine(mode: .toggle)
    check("toggle: first press starts", toggle.handle(.shortcutDown) == .start)
    check("toggle: key-up is ignored", toggle.handle(.shortcutUp) == .none)
    check("toggle: second press stops", toggle.handle(.shortcutDown) == .stop)
}

print(failures == 0 ? "\nAll checks passed." : "\n\(failures) check(s) FAILED.")
exit(failures == 0 ? 0 : 1)
