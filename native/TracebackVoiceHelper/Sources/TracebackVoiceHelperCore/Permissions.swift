import ApplicationServices
import AVFoundation
import Foundation

/// Every permission the helper needs, checked up front so the very first thing a user sees is an
/// explicit state, never a silent failure. Neither permission can be granted programmatically —
/// both require the user to act in System Settings, which `Notify` points them at.
public enum PermissionState: Equatable {
    case granted
    case denied
    case notDetermined
}

public enum Permissions {
    /// CGEvent.tapCreate (the global hotkey listener) requires Accessibility (Input Monitoring
    /// on newer macOS) trust; there is no async "request" API, only a one-time prompt trigger.
    public static func accessibilityState(promptIfNeeded: Bool) -> PermissionState {
        let options: NSDictionary = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: promptIfNeeded]
        return AXIsProcessTrustedWithOptions(options) ? .granted : .denied
    }

    public static func microphoneState() -> PermissionState {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized: return .granted
        case .notDetermined: return .notDetermined
        case .denied, .restricted: return .denied
        @unknown default: return .denied
        }
    }

    public static func requestMicrophone(_ completion: @escaping (Bool) -> Void) {
        AVCaptureDevice.requestAccess(for: .audio, completionHandler: completion)
    }
}
