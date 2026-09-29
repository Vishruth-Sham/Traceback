import CryptoKit
import Foundation

/// Builds the exact `POST /api/v1/voice-captures` request `backend/voice.py::create_voice_capture`
/// expects — same query params, same headers, same atomic-idempotent-upload contract the browser
/// recorder (`frontend/src/lib/voice.ts::voiceIngestPath`) already uses. Pure and network-free, so
/// it can be unit tested without a running backend.
public enum VoiceCaptureRequest {
    public static func sha256Hex(_ data: Data) -> String {
        let digest = SHA256.hash(data: data)
        return digest.map { String(format: "%02x", $0) }.joined()
    }

    public static func iso8601(_ date: Date) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.string(from: date)
    }

    /// `entry_point=global`: the helper always launches from outside any specific app surface.
    public static func build(
        config: Config,
        audio: Data,
        capturedAt: Date,
        sourceTimezone: String,
        durationMs: Int,
        idempotencyKey: String,
        contextualCaptureID: String? = nil
    ) -> URLRequest {
        var components = URLComponents(url: config.apiBaseURL.appendingPathComponent("/api/v1/voice-captures"), resolvingAgainstBaseURL: false)!
        var items = [
            URLQueryItem(name: "size", value: String(audio.count)),
            URLQueryItem(name: "sha256", value: sha256Hex(audio)),
            URLQueryItem(name: "captured_at", value: iso8601(capturedAt)),
            URLQueryItem(name: "source_timezone", value: sourceTimezone),
            URLQueryItem(name: "entry_point", value: "global"),
            URLQueryItem(name: "filename", value: "native-helper.wav"),
            URLQueryItem(name: "duration_ms", value: String(durationMs)),
        ]
        if let contextualCaptureID {
            items.append(URLQueryItem(name: "contextual_capture_id", value: contextualCaptureID))
        }
        components.queryItems = items
        var request = URLRequest(url: components.url!)
        request.httpMethod = "POST"
        request.httpBody = audio
        request.setValue("Bearer \(config.apiToken)", forHTTPHeaderField: "Authorization")
        request.setValue(idempotencyKey, forHTTPHeaderField: "Idempotency-Key")
        request.setValue(config.clientLabel, forHTTPHeaderField: "X-Traceback-Client")
        request.setValue("audio/wav", forHTTPHeaderField: "Content-Type")
        return request
    }
}
