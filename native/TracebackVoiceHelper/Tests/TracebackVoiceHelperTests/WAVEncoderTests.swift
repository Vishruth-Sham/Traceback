import XCTest
@testable import TracebackVoiceHelperCore

final class WAVEncoderTests: XCTestCase {
    func testHeaderDeclaresSixteenKilohertzMonoSixteenBit() {
        let wav = WAVEncoder.encode(pcm16: [1, -1, 100, -100])
        XCTAssertEqual(wav.prefix(4), Data("RIFF".utf8))
        XCTAssertEqual(wav[8..<12], Data("WAVE".utf8))
        let channels = UInt16(wav[22]) | (UInt16(wav[23]) << 8)
        let sampleRate = UInt32(wav[24]) | (UInt32(wav[25]) << 8) | (UInt32(wav[26]) << 16) | (UInt32(wav[27]) << 24)
        let bitsPerSample = UInt16(wav[34]) | (UInt16(wav[35]) << 8)
        XCTAssertEqual(channels, 1)
        XCTAssertEqual(sampleRate, 16000)
        XCTAssertEqual(bitsPerSample, 16)
        XCTAssertEqual(wav.count, 44 + 4 * 2) // header + 4 Int16 samples
    }

    func testEmptySamplesStillProducesAValidHeaderOnlyFile() {
        let wav = WAVEncoder.encode(pcm16: [])
        XCTAssertEqual(wav.count, 44)
    }
}
