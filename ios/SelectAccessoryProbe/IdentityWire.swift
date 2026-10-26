import Foundation

// Only firmware attribute 1: no generic encoder or arbitrary command input.
struct IdentityWire {
    static let request: [UInt8] = [0x48, 0x50, 0x2b, 1, 2, 4, 1]
    private(set) var sent = 0
    private var buffer: [UInt8] = []
    private var total = 0
    enum Failure: Error { case malformed, writeFailed }

    mutating func send(_ writer: ([UInt8]) -> Int) throws -> [UInt8] {
        guard sent < Self.request.count else { return [] }
        let remaining = Array(Self.request[sent...])
        let count = writer(remaining)
        guard count >= 0, count <= remaining.count else { throw Failure.writeFailed }
        sent += count
        return Array(remaining.prefix(count))
    }

    mutating func receive(_ bytes: [UInt8]) throws -> String? {
        total += bytes.count
        guard total <= 4096 else { throw Failure.malformed }
        buffer += bytes
        guard buffer.count >= 4 else { return nil }
        guard Array(buffer.prefix(3)) == [0x48, 0x50, 0x2b], [1, 2].contains(buffer[3]) else { throw Failure.malformed }
        let header = buffer[3] == 1 ? 5 : 6
        guard buffer.count >= header else { return nil }
        let length = Int(buffer[4]) + (header == 6 ? Int(buffer[5]) * 256 : 0)
        guard length > 0, length <= 4090 else { throw Failure.malformed }
        guard buffer.count >= header + length else { return nil }
        // One strict response only; unexpected events/errors are logged raw and stop.
        guard buffer.count == header + length, sent == Self.request.count else { throw Failure.malformed }
        let payload = Array(buffer[header...])
        guard payload.count >= 3, payload[0] == 5, payload[1] == 1 else { throw Failure.malformed }
        var size = 0
        var offset = 2
        var complete = false
        for shift in 0..<5 {
            guard offset < payload.count else { throw Failure.malformed }
            let byte = payload[offset]; offset += 1
            size |= Int(byte & 127) << (shift * 7)
            if byte & 128 == 0 { complete = true; break }
        }
        guard complete, size > 0, size <= 128, payload.count == offset + size else { throw Failure.malformed }
        var text = Array(payload[offset...])
        while text.last == 0 { text.removeLast() }
        guard !text.isEmpty, text.allSatisfy({ $0 >= 32 && $0 <= 126 }),
              let value = String(bytes: text, encoding: .ascii) else { throw Failure.malformed }
        return value
    }
}
