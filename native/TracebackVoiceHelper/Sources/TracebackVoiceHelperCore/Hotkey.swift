import CoreGraphics
import Foundation

/// System-wide key listener via `CGEvent.tapCreate`. This is the piece that needs Accessibility
/// (Input Monitoring) permission: without it, `tapCreate` returns nil and `start()` reports that
/// explicitly rather than silently doing nothing. Traceback is never force-focused by this: the
/// tap only observes and consumes the configured shortcut/Escape, and lets every other key pass
/// through untouched (`.listenOnly` for everything except the exact keys we own).
public final class GlobalHotkeyListener {
    private let config: Config
    private let onEvent: (ShortcutEvent) -> Void
    private var eventTap: CFMachPort?
    private var runLoopSource: CFRunLoopSource?

    public init(config: Config, onEvent: @escaping (ShortcutEvent) -> Void) {
        self.config = config
        self.onEvent = onEvent
    }

    public enum StartError: Error, CustomStringConvertible {
        case accessibilityNotGranted
        public var description: String { "Accessibility (Input Monitoring) permission was not granted; the global shortcut cannot be installed." }
    }

    public func start() throws {
        guard Permissions.accessibilityState(promptIfNeeded: true) == .granted else {
            throw StartError.accessibilityNotGranted
        }
        let mask = (1 << CGEventType.keyDown.rawValue) | (1 << CGEventType.keyUp.rawValue)
        let selfPointer = Unmanaged.passUnretained(self).toOpaque()
        guard let tap = CGEvent.tapCreate(
            tap: .cgSessionEventTap,
            place: .headInsertEventTap,
            options: .defaultTap,
            eventsOfInterest: CGEventMask(mask),
            callback: { _, type, event, refcon in GlobalHotkeyListener.handle(type: type, event: event, refcon: refcon) },
            userInfo: selfPointer
        ) else {
            throw StartError.accessibilityNotGranted
        }
        eventTap = tap
        let source = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, tap, 0)
        runLoopSource = source
        CFRunLoopAddSource(CFRunLoopGetCurrent(), source, .commonModes)
        CGEvent.tapEnable(tap: tap, enable: true)
    }

    public func stop() {
        if let tap = eventTap { CGEvent.tapEnable(tap: tap, enable: false) }
        if let source = runLoopSource { CFRunLoopRemoveSource(CFRunLoopGetCurrent(), source, .commonModes) }
        eventTap = nil
        runLoopSource = nil
    }

    private static func handle(type: CGEventType, event: CGEvent, refcon: UnsafeMutableRawPointer?) -> Unmanaged<CGEvent>? {
        guard let refcon else { return Unmanaged.passUnretained(event) }
        let listener = Unmanaged<GlobalHotkeyListener>.fromOpaque(refcon).takeUnretainedValue()
        let keyCode = Int(event.getIntegerValueField(.keyboardEventKeycode))
        let isShortcutKey = keyCode == listener.config.shortcutKeyCode && (!listener.config.shortcutRequiresOption || event.flags.contains(.maskAlternate))
        let isEscape = keyCode == 53 // kVK_Escape

        if type == .keyDown, isShortcutKey {
            listener.onEvent(.shortcutDown)
            return nil // consumed: never forwarded to whatever app was focused
        }
        if type == .keyUp, isShortcutKey {
            listener.onEvent(.shortcutUp)
            return nil
        }
        if type == .keyDown, isEscape {
            listener.onEvent(.escape)
            return nil
        }
        return Unmanaged.passUnretained(event) // everything else passes through untouched
    }
}
