import Foundation

/// A consumed permit grants only one saved job's journaled upload messages.
/// Read-only traffic remains allowed. No clock/settings/factory commands are added.
struct SingleJobFrameGate {
    private let binding: JobBinding
    private let jpeg: [UInt8]
    private let journal: JobJournal
    private var remaining: [UInt8] = []
    private var seen = Set<String>()
    private(set) var acceptedBytes = 0
    var id: UUID { binding.id }
    var totalBytes: Int { binding.byteCount }
    var acknowledgedBytes: Int { (try? journal.record(binding.id))?.acknowledgedBytes ?? 0 }
    func finish() throws { try journal.finishPrintAttempt(binding.id) }
    init(permit: PrintPermit, journal: JobJournal) throws {
        try permit.consume(in:journal)
        binding = permit.binding; self.journal = journal
        jpeg = Array(try journal.boundImage(binding.id).jpeg)
    }
    mutating func write(_ bytes: [UInt8], writer: ([UInt8]) -> Int) throws -> Int {
        if remaining.isEmpty {
            guard bytes.count >= 5, bytes.prefix(3) == [72,80,43], [1,2].contains(bytes[3]) else { throw JobJournal.Failure.blocked }
            let header = 4 + Int(bytes[3])
            guard bytes.count >= header else { throw JobJournal.Failure.blocked }
            let length = Int(bytes[4]) + (bytes[3] == 2 ? Int(bytes[5])*256 : 0)
            guard length > 0, length <= 4096, bytes.count == header+length else { throw JobJournal.Failure.blocked }
            try authorize(Array(bytes.dropFirst(header))); remaining = bytes
        }
        guard bytes == remaining else { throw JobJournal.Failure.blocked }
        let count = writer(bytes)
        guard count >= 0, count <= bytes.count else { throw JobJournal.Failure.blocked }
        acceptedBytes += count; remaining.removeFirst(count); return count
    }
    private mutating func authorize(_ payload: [UInt8]) throws {
        if ReadOnlyFrameGate.allows(payload) { return }
        guard let opcode = payload.first, [12,14,48].contains(opcode),
              try journal.attemptState(binding.id) == "started",
              let record = try journal.record(binding.id), record.device == binding.device,
              record.digest == binding.digest, record.byteCount == binding.byteCount,
              record.baselineFirmware == binding.firmware, record.pendingOpcode == opcode,
              record.pendingDigest == JobJournal.digest(Data(payload)) else { throw JobJournal.Failure.blocked }
        let key = "\(opcode):\(record.acknowledgedBytes):\(record.printerJobID ?? 0):\(record.handle ?? 0)"
        guard !seen.contains(key) else { throw JobJournal.Failure.blocked }
        switch opcode {
        case 12:
            guard payload == [12,1] + UploadPlan.little(jpeg.count,bytes:4), record.printerJobID == nil else { throw JobJournal.Failure.blocked }
        case 48:
            let name = Array("Select photo".utf8)
            guard let id = record.printerJobID,
                  payload == [48] + UploadPlan.little(Int(id),bytes:2) + [3,1,1,UInt8(name.count)] + name else { throw JobJournal.Failure.blocked }
        case 14:
            guard let handle = record.handle, payload.count >= 2, payload[1] == handle,
                  record.acknowledgedBytes >= 0, record.acknowledgedBytes <= jpeg.count else { throw JobJournal.Failure.blocked }
            let start = record.acknowledgedBytes, count = payload.count-2
            guard (count > 0 || start == jpeg.count), start+count <= jpeg.count,
                  Array(payload.dropFirst(2)) == Array(jpeg[start..<start+count]) else { throw JobJournal.Failure.blocked }
        default: throw JobJournal.Failure.blocked
        }
        seen.insert(key)
    }
}
