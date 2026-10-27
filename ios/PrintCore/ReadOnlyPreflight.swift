import Foundation

/// One framed exchange at a time. No resynchronization, unsolicited events or retries.
struct AccessoryExchange {
    enum Failure: Error { case invalid, timeout, interrupted }
    private var output: [UInt8]
    private var input: [UInt8] = []
    private(set) var sent = 0
    private(set) var ended = false
    private let deadline: TimeInterval
    init(payload: [UInt8], now: TimeInterval) throws {
        guard !payload.isEmpty, payload.count <= 4096, now.isFinite else { throw Failure.invalid }
        output = [72,80,43] + (payload.count < 256 ? [1,UInt8(payload.count)] : [2,UInt8(payload.count & 255),UInt8(payload.count >> 8)]) + payload
        deadline = now + 10
    }
    mutating func check(now: TimeInterval) throws {
        guard !ended, now.isFinite, now < deadline else { ended = true; throw Failure.timeout }
    }
    mutating func stop() { ended = true }
    mutating func write(now: TimeInterval, _ writer: ([UInt8]) -> Int) throws {
        try check(now: now)
        guard sent < output.count else { return }
        let remaining = Array(output[sent...]), count = writer(Array(output[sent...]))
        guard count >= 0, count <= remaining.count else { ended = true; throw Failure.interrupted }
        sent += count
    }
    mutating func receive(_ bytes: [UInt8], now: TimeInterval) throws -> [UInt8]? {
        try check(now: now)
        do {
            guard sent == output.count, input.count + bytes.count <= 4104 else { throw Failure.invalid }
            input += bytes
            guard input.count >= 4 else { return nil }
            guard Array(input.prefix(3)) == [72,80,43], (1...3).contains(input[3]) else { throw Failure.invalid }
            let width = [1:1,2:2,3:4][Int(input[3])]!, header = 4 + [1:1,2:2,3:4][Int(input[3])]!
            guard input.count >= header else { return nil }
            let count = (0..<width).reduce(0) { $0 | (Int(input[4+$1]) << (8*$1)) }
            guard count > 0, count <= 4096, input.count <= header + count else { throw Failure.invalid }
            guard input.count == header + count else { return nil }
            ended = true
            return Array(input[header...])
        } catch { ended = true; throw error }
    }
}

/// Fixed read-only allowlist plus connection-local maximum negotiation. No print opcodes.
struct ReadOnlyPreflight {
    enum Failure: Error { case invalid(String) }
    private enum Stage { case firmware, model, device, setup, feature, download, pause, status, jobs, metrics, done }
    private var stage: Stage = .firmware
    private var pending = false
    private(set) var failed = false
    private(set) var complete = false
    private(set) var firmware = ""
    private(set) var deviceID = ""
    private(set) var maximum = 0
    private(set) var setupSecurityRaw: UInt8 = 0
    private(set) var nameLimit = 0
    private(set) var battery = 0
    private(set) var pages = 0
    private(set) var calibrations = 0
    private let expectedID: String?
    private var handle: UInt8 = 0, encoding: UInt8 = 0
    private var table: [UInt8] = [], chunks = 0, previousRemaining: Int?
    private var iterator = 0, iterators = Set<Int>(), counters: [Int:Int] = [:]
    init(expectedDeviceID: String? = nil) throws {
        if let id = expectedDeviceID {
            guard id.count == 32, id.allSatisfy({ "0123456789abcdef".contains($0) }) else { throw Failure.invalid("Invalid expected device identity") }
        }
        expectedID = expectedDeviceID
    }
    var identityBound: Bool { expectedID != nil }
    var summary: String {
        "Read-only checks passed: firmware \(firmware), battery \(battery)%, idle/empty queue, no flags, not paused; maximum \(maximum), setup byte \(setupSecurityRaw), name limit \(nameLimit), pages \(pages), calibration cycles \(calibrations). " + (identityBound ? "Expected device identity matched." : "Identity discovered; not yet bound to a saved job.") + " No print authorized or sent."
    }
    mutating func stop() { failed = true }
    private func require(_ condition: Bool, _ reason: String) throws { if !condition { throw Failure.invalid(reason) } }
    private func number(_ bytes: ArraySlice<UInt8>) -> Int { bytes.enumerated().reduce(0) { $0 | (Int($1.element) << (8*$1.offset)) } }
    mutating func next() throws -> [UInt8] {
        try require(!failed && !complete && !pending, "Stopped, finished or outstanding request")
        pending = true
        switch stage {
        case .firmware: return [4,1]
        case .model: return [4,9]
        case .device: return [4,6]
        case .setup: return [36,0,16] // connection-local max; do not guess iAP interface-select opcode
        case .feature: return [42]
        case .download: return [40,handle,1]
        case .pause: return [26,4]
        case .status: return [8,1,2,3,5,6,7]
        case .jobs: return [44]
        case .metrics: return [58,1,UInt8(iterator & 255),UInt8(iterator >> 8)]
        case .done: throw Failure.invalid("Finished")
        }
    }
    mutating func accept(_ r: [UInt8]) throws {
        do { try decode(r); pending = false }
        catch { failed = true; throw error }
    }
    private mutating func decode(_ r: [UInt8]) throws {
        try require(pending && !failed, "No outstanding request")
        switch stage {
        case .firmware:
            try require(r.count >= 3 && r[0] == 5 && r[1] == 1, "Firmware response")
            var p = 2; let count = try variable(r, &p)
            try require(count > 0 && count <= 128 && p + count == r.count, "Firmware length")
            var raw = Array(r[p...])
            while raw.last == 0 { raw.removeLast() }
            try require(!raw.isEmpty && raw.allSatisfy { (32...126).contains($0) }, "Firmware text")
            firmware = String(decoding: raw, as: UTF8.self); stage = .model
        case .model:
            try require(r == [5,9,211,72], "Not a Select model"); stage = .device
        case .device:
            try require(r.count == 18 && r.prefix(2) == [5,6], "Device identity response")
            deviceID = r.dropFirst(2).map { String(format:"%02x",$0) }.joined()
            try require(expectedID == nil || expectedID == deviceID, "Wrong physical printer"); stage = .setup
        case .setup:
            try require(r.count == 4 && r[0] == 37, "Malformed connection setup: \(r.map { String(format: "%02x", $0) }.joined())")
            setupSecurityRaw = r[3]
            // 0x21 is observed on the same FA printer over desktop transports.
            // Preserve the byte as opaque; do not infer authentication semantics.
            try require([0,33].contains(setupSecurityRaw), "Unrecognized setup byte: \(setupSecurityRaw); reply \(r.map { String(format: "%02x", $0) }.joined())")
            maximum = number(r[1...2]); try require((16...4096).contains(maximum), "Unsafe message maximum"); stage = .feature
        case .feature:
            try require(r.count == 3 && r[0] == 43 && [1,2].contains(r[2]), "Capability discovery")
            handle = r[1]; encoding = r[2]; stage = .download
        case .download:
            try require(r.count >= 6 && r[0] == 41 && r[1] == handle, "Capability handle/header")
            let remaining = number(r[2...5]), amount = r.count - 6
            chunks += 1
            try require(chunks <= 64 && table.count + amount + remaining <= 65536, "Capability bounds")
            if let previousRemaining { try require(previousRemaining == amount + remaining, "Capability remaining length changed") }
            try require(remaining == 0 || amount > 0, "Capability download stalled")
            previousRemaining = remaining; table += r.dropFirst(6)
            if remaining == 0 { try validateTable(); stage = .pause }
        case .pause:
            try require(r == [27,4,0], "Paused or unknown pause state"); stage = .status
        case .status:
            try require(r.first == 9, "Status response")
            let widths: [UInt8:Int] = [1:4,2:1,3:1,5:2,6:1,7:1]
            var fields: [UInt8:Int] = [:], p = 1
            while p < r.count {
                let tag = r[p]; p += 1
                guard let width = widths[tag], fields[tag] == nil, p + width <= r.count else { throw Failure.invalid("Unknown/duplicate/truncated status") }
                fields[tag] = number(r[p..<p+width]); p += width
            }
            try require(fields.count == widths.count && fields[1] == 0 && fields[2] == 1 && fields[5] == 0 && fields[7] == 1, "Printer not idle/empty/error-free")
            battery = fields[3] ?? 0
            try require((30...100).contains(battery) && [1,2].contains(fields[6] ?? 0), "Battery/power unsuitable"); stage = .jobs
        case .jobs:
            try require(r == [45], "Queue not empty or malformed"); stage = .metrics
        case .metrics:
            try require(r.count >= 4 && r[0] == 59 && r[1] == 1 && (r.count - 4) % 6 == 0, "Metrics response")
            try require(iterators.insert(iterator).inserted && iterators.count <= 16, "Metrics loop/bound")
            for p in stride(from: 4, to: r.count, by: 6) {
                let key = number(r[p..<p+2]); try require(counters[key] == nil, "Duplicate metric")
                counters[key] = number(r[p+2..<p+6])
            }
            iterator = number(r[2...3])
            if iterator == 0 {
                guard let pageCount = counters[1], let calibrationCount = counters[3] else { throw Failure.invalid("Counters missing") }
                pages = pageCount; calibrations = calibrationCount; complete = true; stage = .done
            } else { try require(!iterators.contains(iterator) && iterators.count < 16, "Metrics loop/bound") }
        case .done: throw Failure.invalid("Unexpected response")
        }
    }
    private func variable(_ data: [UInt8], _ p: inout Int) throws -> Int {
        var value = 0
        for shift in 0..<5 {
            try require(p < data.count, "Truncated variable integer")
            let b = data[p]; p += 1; value |= Int(b & 127) << (7*shift)
            if b < 128 { return value }
        }
        throw Failure.invalid("Variable integer too long")
    }
    private mutating func validateTable() throws {
        var values: [Int:[Int]] = [:]
        if encoding == 1 {
            struct Features: Decodable {
                let requests: [Int]
                let mime: [Int]
                let job_prop: [Int]
                let job_name_max: Int
            }
            let object = try JSONDecoder().decode(Features.self, from: Data(table))
            values[3] = object.requests; values[7] = object.mime; values[8] = object.job_prop
            nameLimit = object.job_name_max
        } else {
            var p = 0, seen = Set<Int>()
            while p < table.count {
                try require(p+3 <= table.count, "Truncated capability TLV")
                let tag = Int(table[p]), length = number(table[p+1...p+2]); p += 3
                try require(p+length <= table.count && seen.insert(tag).inserted, "Capability TLV length/duplicate")
                let raw = Array(table[p..<p+length]); p += length
                if [3,7,8].contains(tag) {
                    var start = 0; let count = try variable(raw, &start)
                    try require(start+count == raw.count, "Capability array length"); values[tag] = raw.dropFirst(start).map(Int.init)
                } else if tag == 20 { try require(raw.count == 2, "Name limit width"); nameLimit = number(raw[...]) }
            }
        }
        try require(Set([12,14,48,44,58]).isSubset(of: Set(values[3] ?? [])) && Set([1,3]).isSubset(of: Set(values[8] ?? [])) && (values[7] ?? []).contains(1) && (1...65535).contains(nameLimit), "Required printing capabilities absent")
    }
}
