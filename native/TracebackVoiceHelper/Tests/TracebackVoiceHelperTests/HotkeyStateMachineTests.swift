import XCTest
@testable import TracebackVoiceHelperCore

final class HotkeyStateMachineTests: XCTestCase {
    func testPushToTalkStartsOnDownAndStopsOnUp() {
        var machine = HotkeyStateMachine(mode: .pushToTalk)
        XCTAssertEqual(machine.handle(.shortcutDown), .start)
        XCTAssertEqual(machine.handle(.shortcutUp), .stop)
    }

    func testPushToTalkIgnoresKeyRepeatWhileAlreadyRecording() {
        var machine = HotkeyStateMachine(mode: .pushToTalk)
        XCTAssertEqual(machine.handle(.shortcutDown), .start)
        XCTAssertEqual(machine.handle(.shortcutDown), .none) // OS key-repeat, not a second press
        XCTAssertEqual(machine.handle(.shortcutUp), .stop)
    }

    func testPushToTalkEscapeCancelsAndClearsRecordingState() {
        var machine = HotkeyStateMachine(mode: .pushToTalk)
        _ = machine.handle(.shortcutDown)
        XCTAssertEqual(machine.handle(.escape), .cancel)
        XCTAssertFalse(machine.isRecording)
        XCTAssertEqual(machine.handle(.shortcutUp), .none) // already stopped by Esc; key-up is a no-op
    }

    func testEscapeWhileIdleDoesNothing() {
        var machine = HotkeyStateMachine(mode: .pushToTalk)
        XCTAssertEqual(machine.handle(.escape), .none)
    }

    func testToggleStartsOnFirstPressAndStopsOnSecondPressIgnoringKeyUp() {
        var machine = HotkeyStateMachine(mode: .toggle)
        XCTAssertEqual(machine.handle(.shortcutDown), .start)
        XCTAssertEqual(machine.handle(.shortcutUp), .none)
        XCTAssertEqual(machine.handle(.shortcutDown), .stop)
        XCTAssertEqual(machine.handle(.shortcutUp), .none)
    }

    func testToggleEscapeAlsoCancels() {
        var machine = HotkeyStateMachine(mode: .toggle)
        _ = machine.handle(.shortcutDown)
        XCTAssertEqual(machine.handle(.escape), .cancel)
        XCTAssertEqual(machine.handle(.shortcutDown), .start) // a fresh recording can start again after cancel
    }
}
