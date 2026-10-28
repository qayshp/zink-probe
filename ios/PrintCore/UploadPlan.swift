import Foundation

/// Transport-independent one-copy upload sequencing.
/// Input must come from validated image preparation; this layer does not decode JPEG.
/// No retry, reconnect, resume, settings change or assertion of physical completion.
struct UploadPlan {
    enum Phase: String { case start, properties, upload, uploaded, stopped }
    enum Failure: Error { case invalidInput, invalidTransition, malformedReply, rejected(UInt8) }
    private(set) var phase: Phase = .start
    private(set) var offset = 0
    private(set) var jobID: UInt16?
    private(set) var handle: UInt8?
    private var pending: [UInt8]?
    private var emptySent = false
    private let jpeg: [UInt8]
    private let maximum: Int
    private let properties: [UInt8]

    init(preparedJPEG: Data, maximum: Int, name: String, nameLimit: Int) throws {
        let bytes = Array(preparedJPEG), nameBytes = Array(name.utf8)
        let maximum = min(maximum, 4096)
        guard bytes.count >= 4, bytes.count <= 16 * 1024 * 1024,
              bytes.starts(with: [255,216]), bytes.suffix(2) == [255,217],
              maximum >= 6, nameLimit >= 0, !name.isEmpty,
              !name.unicodeScalars.contains(where: { $0.value < 32 }),
              nameBytes.count <= nameLimit else { throw Failure.invalidInput }
        var length = nameBytes.count, encoded: [UInt8] = []
        repeat {
            let low = UInt8(length & 127); length >>= 7
            encoded.append(low | (length > 0 ? 128 : 0))
        } while length > 0
        let properties: [UInt8] = [3,1,1] + encoded + nameBytes // exactly one copy
        guard 3 + properties.count <= maximum else { throw Failure.invalidInput }
        self.jpeg = bytes; self.maximum = maximum; self.properties = properties
    }

    static func little(_ value: Int, bytes: Int) -> [UInt8] {
        (0..<bytes).map { UInt8((value >> ($0 * 8)) & 255) }
    }
    private static func number(_ bytes: ArraySlice<UInt8>) -> Int {
        bytes.enumerated().reduce(0) { $0 | (Int($1.element) << ($1.offset * 8)) }
    }

    mutating func nextMessage() throws -> [UInt8] {
        guard pending == nil else { throw Failure.invalidTransition }
        let message: [UInt8]
        switch phase {
        case .start: message = [12,1] + Self.little(jpeg.count, bytes: 4)
        case .properties:
            guard let jobID else { throw Failure.invalidTransition }
            message = [48] + Self.little(Int(jobID), bytes: 2) + properties
        case .upload:
            guard let handle else { throw Failure.invalidTransition }
            let chunk = Array(jpeg[offset..<min(jpeg.count, offset + maximum - 2)])
            guard !chunk.isEmpty || !emptySent else { phase = .stopped; throw Failure.invalidTransition }
            emptySent = emptySent || chunk.isEmpty
            message = [14,handle] + chunk
        case .uploaded, .stopped: throw Failure.invalidTransition
        }
        pending = message
        return message
    }

    /// A failed/ambiguous exchange terminates this instance; never retransmit it.
    mutating func stop() { phase = .stopped; pending = nil }

    mutating func accept(_ reply: [UInt8]) throws {
        do { try validateAndAccept(reply) }
        catch { stop(); throw error }
    }
    private mutating func validateAndAccept(_ reply: [UInt8]) throws {
        guard let request = pending, phase != .stopped else { throw Failure.invalidTransition }
        if reply.first == 1 {
            guard reply.count == 3, reply[1] == request[0] else { throw Failure.malformedReply }
            throw Failure.rejected(reply[2])
        }
        guard reply.first == request[0] + 1 else { throw Failure.malformedReply }
        switch phase {
        case .start:
            guard reply.count == 4 else { throw Failure.malformedReply }
            let id = Self.number(reply[2...3])
            guard id != 0 else { throw Failure.malformedReply }
            handle = reply[1]; jobID = UInt16(id); phase = .properties
        case .properties:
            guard reply == [49] else { throw Failure.malformedReply }
            phase = .upload
        case .upload:
            guard reply.count == 11, reply[1] == handle else { throw Failure.malformedReply }
            let received = Self.number(reply[3...6]), total = Self.number(reply[7...10])
            guard total == jpeg.count, received == offset + request.count - 2,
                  [1,2].contains(reply[2]), reply[2] != 2 || received == total else { throw Failure.malformedReply }
            offset = received
            if reply[2] == 2 { phase = .uploaded }
        default: throw Failure.invalidTransition
        }
        pending = nil
    }
}
