// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "TracebackVoiceHelper",
    platforms: [.macOS(.v13)],
    targets: [
        // All logic lives here so both the real CLI and the (XCTest-free) self-test executable
        // can depend on it as an ordinary library, rather than one executable importing another
        // (which SwiftPM does not reliably link).
        .target(name: "TracebackVoiceHelperCore", path: "Sources/TracebackVoiceHelperCore"),
        .executableTarget(name: "TracebackVoiceHelper", dependencies: ["TracebackVoiceHelperCore"], path: "Sources/TracebackVoiceHelper"),
        .testTarget(name: "TracebackVoiceHelperTests", dependencies: ["TracebackVoiceHelperCore"], path: "Tests/TracebackVoiceHelperTests"),
        // Runs the same pure-logic checks as TracebackVoiceHelperTests via plain assertions
        // instead of XCTest, for toolchains with only Command Line Tools installed (no Xcode.app,
        // no XCTest.framework) — see native/README.md "Known limitation".
        .executableTarget(name: "TracebackVoiceHelperSelfTest", dependencies: ["TracebackVoiceHelperCore"], path: "Sources/TracebackVoiceHelperSelfTest"),
    ]
)
