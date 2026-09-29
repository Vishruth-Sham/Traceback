import AVFoundation
import Foundation

/// Captures the microphone into 16 kHz mono PCM16 while active, converting from whatever the
/// input device's native format is. This is the one piece of the helper that genuinely cannot be
/// exercised in an automated test: it needs a real audio input device and, the first time, the
/// user's explicit consent in a system dialog.
public final class Recorder {
    private let engine = AVAudioEngine()
    private var converter: AVAudioConverter?
    private var samples: [Int16] = []
    private let targetFormat = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16000, channels: 1, interleaved: true)!
    private(set) var startedAt: Date?

    public init() {}

    public func start() throws {
        samples.removeAll()
        let input = engine.inputNode
        let inputFormat = input.outputFormat(forBus: 0)
        converter = AVAudioConverter(from: inputFormat, to: targetFormat)
        input.installTap(onBus: 0, bufferSize: 2048, format: inputFormat) { [weak self] buffer, _ in
            self?.consume(buffer, from: inputFormat)
        }
        engine.prepare()
        try engine.start()
        startedAt = Date()
    }

    /// Stops capture and returns (wavBytes, durationMs). Returns nil audio when nothing was captured.
    public func stop() -> (Data, Int)? {
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        let durationMs = startedAt.map { Int(Date().timeIntervalSince($0) * 1000) } ?? 0
        startedAt = nil
        guard !samples.isEmpty else { return nil }
        let wav = WAVEncoder.encode(pcm16: samples)
        samples.removeAll()
        return (wav, durationMs)
    }

    public func cancel() {
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        samples.removeAll()
        startedAt = nil
    }

    private func consume(_ buffer: AVAudioPCMBuffer, from inputFormat: AVAudioFormat) {
        guard let converter else { return }
        let ratio = targetFormat.sampleRate / inputFormat.sampleRate
        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * ratio) + 16
        guard let output = AVAudioPCMBuffer(pcmFormat: targetFormat, frameCapacity: capacity) else { return }
        var error: NSError?
        var consumed = false
        converter.convert(to: output, error: &error) { _, status in
            if consumed {
                status.pointee = .noDataNow
                return nil
            }
            consumed = true
            status.pointee = .haveData
            return buffer
        }
        guard error == nil, let channel = output.int16ChannelData else { return }
        let frames = Int(output.frameLength)
        samples.append(contentsOf: UnsafeBufferPointer(start: channel[0], count: frames))
    }
}
