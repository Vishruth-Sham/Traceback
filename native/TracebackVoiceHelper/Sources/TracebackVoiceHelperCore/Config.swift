import Foundation

/// Mirrors `processor.runner.RunnerConfig`: the same loopback backend, the same token, the
/// same env var names, so the helper needs no configuration beyond what the processor already
/// reads from `.env`. No cloud endpoint is ever accepted.
///
/// Public so the plain-assertion self-test executable (see `TracebackVoiceHelperSelfTest`) can
/// exercise it without `@testable import`, which only test targets get.
public struct Config: Equatable {
    public enum ConfigError: Error, Equatable, CustomStringConvertible {
        case missingToken
        case notLoopback(String)

        public var description: String {
            switch self {
            case .missingToken:
                return "TRACEBACK_API_TOKEN is not set. Export it (or add it to .env) before running the helper."
            case .notLoopback(let url):
                return "TRACEBACK_PROCESSOR_API_BASE_URL (\(url)) must be plain HTTP on a loopback address."
            }
        }
    }

    public enum ShortcutMode: String, Equatable {
        /// Hold to record, release to send, Esc to cancel.
        case pushToTalk = "push_to_talk"
        /// Press once to start, press again to stop (the accessibility-friendly mode).
        case toggle = "toggle"
    }

    public var apiBaseURL: URL
    public var apiToken: String
    public var clientLabel: String
    public var shortcutMode: ShortcutMode
    /// Carbon/CGEvent modifier flags + a virtual keycode, e.g. Option (0x800000 -> .maskAlternate) + Space (49).
    public var shortcutKeyCode: Int
    public var shortcutRequiresOption: Bool

    public static func isLoopback(_ url: URL) -> Bool {
        guard url.scheme == "http", let host = url.host else { return false }
        return host == "localhost" || host == "127.0.0.1" || host == "::1"
    }

    public static func load(from environment: [String: String]) throws -> Config {
        guard let token = environment["TRACEBACK_API_TOKEN"], !token.isEmpty else {
            throw ConfigError.missingToken
        }
        let base = environment["TRACEBACK_PROCESSOR_API_BASE_URL"] ?? "http://127.0.0.1:8000"
        guard let url = URL(string: base), isLoopback(url) else {
            throw ConfigError.notLoopback(base)
        }
        let modeRaw = environment["TRACEBACK_VOICE_HELPER_MODE"] ?? ShortcutMode.pushToTalk.rawValue
        let mode = ShortcutMode(rawValue: modeRaw) ?? .pushToTalk
        // Default: Option+Space (kVK_Space = 49), matching the design system's documented default.
        let keyCode = Int(environment["TRACEBACK_VOICE_HELPER_KEYCODE"] ?? "49") ?? 49
        return Config(apiBaseURL: url, apiToken: token, clientLabel: "native-helper", shortcutMode: mode, shortcutKeyCode: keyCode, shortcutRequiresOption: true)
    }
}
