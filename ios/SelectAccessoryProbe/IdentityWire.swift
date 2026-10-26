import Foundation

// Two fixed read-only requests only: firmware identity or status. No arbitrary encoder.
struct IdentityWire {
    static let request: [UInt8] = [0x48, 0x50, 0x2b, 1, 2, 4, 1]
    enum Mode { case identity, status }
    let mode: Mode
    init(mode: Mode = .identity) { self.mode = mode }
    var requestBytes: [UInt8] { mode == .identity ? Self.request : [0x48,0x50,0x2b,1,5,8,1,2,3,6] }
    private(set) var status: PrinterStatus?
    private(set) var sent = 0
    private var buffer: [UInt8] = []
    private var total = 0
    enum Failure: Error { case malformed, writeFailed }

    mutating func send(_ writer: ([UInt8]) -> Int) throws -> [UInt8] {
        guard sent < requestBytes.count else { return [] }
        let remaining = Array(requestBytes[sent...])
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
        guard buffer.count == header + length, sent == requestBytes.count else { throw Failure.malformed }
        let payload = Array(buffer[header...])
        if mode == .status {
            status = try PrinterStatus.decode(payload)
            return "Status received"
        }
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


struct PrinterStatus {
    let battery: UInt8
    let power: UInt8
    let state: UInt8
    let flags: UInt32
    var charging: String {
        [1: "In use (not charging)", 2: "Charging / external power", 3: "Overheated", 4: "Battery error"][Int(power)] ?? "Unknown (\(power))"
    }
    var printer: String {
        let names = ["Idle", "Preparing", "Out of paper", "Paper jam", "Calibrating", "Tray open", "Printing", "Overheating", "Feed path obstructed", "Out of supplies", "No supplies detected", "No tray", "Tray misaligned", "Unrecoverable error", "Battery critical", "Paper pick", "Multiple-page pick"]
        return state >= 1 && Int(state) <= names.count ? names[Int(state)-1] : "Unknown (\(state))"
    }
    var alerts: String {
        var values: [String] = []
        for (bit, name) in ["Clock invalid", "Battery critical", "Print busy", "Out of paper", "Low on supplies"].enumerated() {
            if flags & (1 << bit) != 0 { values.append(name) }
        }
        let unknown = flags & ~UInt32(31)
        if unknown != 0 { values.append(String(format: "Unknown flags 0x%08X", unknown)) }
        if ![1,2,5,7,16].contains(Int(state)) { values.append(printer) }
        if power == 3 || power == 4 || !(1...4).contains(power) { values.append(charging) }
        return values.isEmpty ? "No alerts in queried fields" : values.joined(separator: "; ")
    }
    static func decode(_ payload: [UInt8]) throws -> PrinterStatus {
        guard payload.first == 9 else { throw IdentityWire.Failure.malformed }
        var fields: [UInt8: UInt32] = [:]
        var offset = 1
        while offset < payload.count {
            let tag = payload[offset]; offset += 1
            guard [1,2,3,6].contains(tag), fields[tag] == nil else { throw IdentityWire.Failure.malformed }
            let width = tag == 1 ? 4 : 1
            guard offset + width <= payload.count else { throw IdentityWire.Failure.malformed }
            var value: UInt32 = 0
            for i in 0..<width { value |= UInt32(payload[offset+i]) << (8*i) }
            fields[tag] = value; offset += width
        }
        guard fields.count == 4, let battery = fields[3], battery <= 100,
              let power = fields[6], let state = fields[2], let flags = fields[1] else { throw IdentityWire.Failure.malformed }
        return PrinterStatus(battery: UInt8(battery), power: UInt8(power), state: UInt8(state), flags: flags)
    }
}
