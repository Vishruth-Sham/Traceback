import XCTest
@testable import TracebackVoiceHelperCore

final class VoiceCaptureRequestTests: XCTestCase {
    func testMatchesTheBackendsExpectedContract() throws {
        let config = try Config.load(from: ["TRACEBACK_API_TOKEN": "s3cret"])
        let audio = Data("fake-wav-bytes".utf8)
        let request = VoiceCaptureRequest.build(
            config: config,
            audio: audio,
            capturedAt: Date(timeIntervalSince1970: 1_790_000_000),
            sourceTimezone: "Asia/Kolkata",
            durationMs: 4200,
            idempotencyKey: "idem-123"
        )

        XCTAssertEqual(request.httpMethod, "POST")
        XCTAssertEqual(request.url?.path, "/api/v1/voice-captures")
        XCTAssertEqual(request.httpBody, audio)
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer s3cret")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Idempotency-Key"), "idem-123")
        XCTAssertEqual(request.value(forHTTPHeaderField: "X-Traceback-Client"), "native-helper")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Content-Type"), "audio/wav")

        let query = Dictionary(uniqueKeysWithValues: URLComponents(url: request.url!, resolvingAgainstBaseURL: false)!.queryItems!.map { ($0.name, $0.value) })
        XCTAssertEqual(query["size"], String(audio.count))
        XCTAssertEqual(query["sha256"], VoiceCaptureRequest.sha256Hex(audio))
        XCTAssertEqual(query["source_timezone"], "Asia/Kolkata")
        XCTAssertEqual(query["entry_point"], "global") // never pulls Traceback to any specific in-app surface
        XCTAssertEqual(query["duration_ms"], "4200")
        XCTAssertNil(query["contextual_capture_id"]) // omitted, not sent as empty, when there is no follow-up context
    }

    func testAttachesFollowupContextWhenGiven() throws {
        let config = try Config.load(from: ["TRACEBACK_API_TOKEN": "s3cret"])
        let request = VoiceCaptureRequest.build(
            config: config, audio: Data("x".utf8), capturedAt: Date(), sourceTimezone: "UTC",
            durationMs: 100, idempotencyKey: "k", contextualCaptureID: "cap-ambiguous"
        )
        let query = Dictionary(uniqueKeysWithValues: URLComponents(url: request.url!, resolvingAgainstBaseURL: false)!.queryItems!.map { ($0.name, $0.value) })
        XCTAssertEqual(query["contextual_capture_id"], "cap-ambiguous")
    }

    func testSha256IsStableAndLowercaseHex() {
        let digest = VoiceCaptureRequest.sha256Hex(Data("hello".utf8))
        XCTAssertEqual(digest, "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824")
        XCTAssertEqual(digest, digest.lowercased())
    }
}
