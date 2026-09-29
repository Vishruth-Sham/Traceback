import Foundation
import UserNotifications

/// All user-visible feedback is text on screen (a banner) or a printed status line — never
/// speech/TTS, per the design system's "no spoken response" rule. `UNUserNotificationCenter`
/// requires a signed app bundle to post notifications reliably; running from a bare SwiftPM
/// binary, `osascript` is the dependable fallback every Mac already has.
public enum Notify {
    public static func banner(title: String, body: String) {
        FileHandle.standardError.write("[\(title)] \(body)\n".data(using: .utf8)!)
        let script = "display notification \(quoted(body)) with title \(quoted(title))"
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        process.arguments = ["-e", script]
        try? process.run()
    }

    private static func quoted(_ value: String) -> String {
        "\"" + value.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"") + "\""
    }

    public static func status(_ line: String) {
        print("[traceback-voice-helper] \(line)")
        fflush(stdout)
    }
}
