import Foundation

/// Sends the built request over the loopback network. The only network-touching piece besides
/// `Recorder`'s device access; kept thin so `VoiceCaptureRequest` (the actual contract) stays
/// fully unit tested without a running backend.
public enum BackendClient {
    public enum UploadResult {
        case created(captureID: String?)
        case httpError(status: Int, body: String)
        case transportError(String)
    }

    public static func upload(_ request: URLRequest, completion: @escaping (UploadResult) -> Void) {
        let task = URLSession.shared.dataTask(with: request) { data, response, error in
            if let error {
                completion(.transportError(error.localizedDescription))
                return
            }
            guard let http = response as? HTTPURLResponse else {
                completion(.transportError("no HTTP response"))
                return
            }
            let body = data.flatMap { String(data: $0, encoding: .utf8) } ?? ""
            guard (200..<300).contains(http.statusCode) else {
                completion(.httpError(status: http.statusCode, body: body))
                return
            }
            let captureID = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }.flatMap { $0["id"] as? String }
            completion(.created(captureID: captureID))
        }
        task.resume()
    }
}
