import Foundation

/// Wraps raw 16-bit PCM samples in a canonical WAV header. Pure and allocation-only, so it is
/// unit tested directly; `Recorder` is the only caller that supplies real microphone samples.
public enum WAVEncoder {
    public static func encode(pcm16: [Int16], sampleRate: UInt32 = 16000, channels: UInt16 = 1) -> Data {
        let bytesPerSample: UInt16 = 2
        let blockAlign = channels * bytesPerSample
        let byteRate = sampleRate * UInt32(blockAlign)
        let dataSize = UInt32(pcm16.count * Int(bytesPerSample))

        var data = Data()
        data.append(contentsOf: Array("RIFF".utf8))
        data.append(littleEndian: UInt32(36 + dataSize))
        data.append(contentsOf: Array("WAVE".utf8))
        data.append(contentsOf: Array("fmt ".utf8))
        data.append(littleEndian: UInt32(16)) // PCM fmt chunk size
        data.append(littleEndian: UInt16(1)) // PCM format tag
        data.append(littleEndian: channels)
        data.append(littleEndian: sampleRate)
        data.append(littleEndian: byteRate)
        data.append(littleEndian: blockAlign)
        data.append(littleEndian: UInt16(bytesPerSample * 8))
        data.append(contentsOf: Array("data".utf8))
        data.append(littleEndian: dataSize)
        for sample in pcm16 {
            data.append(littleEndian: UInt16(bitPattern: sample))
        }
        return data
    }
}

private extension Data {
    mutating func append(littleEndian value: UInt32) {
        Swift.withUnsafeBytes(of: value.littleEndian) { append(contentsOf: $0) }
    }
    mutating func append(littleEndian value: UInt16) {
        Swift.withUnsafeBytes(of: value.littleEndian) { append(contentsOf: $0) }
    }
}
