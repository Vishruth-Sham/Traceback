import XCTest
@testable import TracebackVoiceHelperCore

final class ConfigTests: XCTestCase {
    func testMissingTokenIsReportedNotSilentlyDefaulted() {
        XCTAssertThrowsError(try Config.load(from: [:])) { error in
            XCTAssertEqual(error as? Config.ConfigError, .missingToken)
        }
    }

    func testDefaultsToTheLoopbackBackendAndPushToTalk() throws {
        let config = try Config.load(from: ["TRACEBACK_API_TOKEN": "secret"])
        XCTAssertEqual(config.apiBaseURL.absoluteString, "http://127.0.0.1:8000")
        XCTAssertEqual(config.shortcutMode, .pushToTalk)
        XCTAssertEqual(config.shortcutKeyCode, 49) // kVK_Space
        XCTAssertTrue(config.shortcutRequiresOption)
    }

    func testRejectsANonLoopbackBaseURL() {
        XCTAssertThrowsError(try Config.load(from: ["TRACEBACK_API_TOKEN": "x", "TRACEBACK_PROCESSOR_API_BASE_URL": "https://example.com"])) { error in
            XCTAssertEqual(error as? Config.ConfigError, .notLoopback("https://example.com"))
        }
    }

    func testHonorsAnExplicitToggleMode() throws {
        let config = try Config.load(from: ["TRACEBACK_API_TOKEN": "x", "TRACEBACK_VOICE_HELPER_MODE": "toggle"])
        XCTAssertEqual(config.shortcutMode, .toggle)
    }

    func testAnUnrecognizedModeFallsBackToPushToTalkRatherThanCrashing() throws {
        let config = try Config.load(from: ["TRACEBACK_API_TOKEN": "x", "TRACEBACK_VOICE_HELPER_MODE": "sing-it"])
        XCTAssertEqual(config.shortcutMode, .pushToTalk)
    }
}
