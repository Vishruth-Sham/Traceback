import Foundation

/// Pure decision logic for turning raw shortcut key events into recorder actions, for both
/// configured modes. Kept separate from the real `CGEventTap` listener so it is unit testable
/// without a running event tap (which needs Accessibility permission and a live session).
public enum RecorderAction: Equatable {
    case start
    case stop
    case cancel
    case none
}

public enum ShortcutEvent: Equatable {
    case shortcutDown
    case shortcutUp
    case escape
}

public struct HotkeyStateMachine {
    public private(set) var isRecording = false
    public let mode: Config.ShortcutMode

    public init(mode: Config.ShortcutMode) {
        self.mode = mode
    }

    /// Feeds one raw event and returns what the recorder should do. Mutates `isRecording` to
    /// track the machine's own notion of state, independent of the real recorder's async state.
    public mutating func handle(_ event: ShortcutEvent) -> RecorderAction {
        switch event {
        case .escape:
            guard isRecording else { return .none }
            isRecording = false
            return .cancel
        case .shortcutDown:
            switch mode {
            case .pushToTalk:
                guard !isRecording else { return .none } // key-repeat while already down
                isRecording = true
                return .start
            case .toggle:
                isRecording.toggle()
                return isRecording ? .start : .stop
            }
        case .shortcutUp:
            switch mode {
            case .pushToTalk:
                guard isRecording else { return .none }
                isRecording = false
                return .stop
            case .toggle:
                return .none // toggle mode ignores key-up entirely
            }
        }
    }
}
