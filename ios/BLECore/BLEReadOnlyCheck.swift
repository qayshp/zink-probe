import Foundation

/// A BLE notification is one packet, not an arbitrary slice of an ATT packet.
/// This codec adds/removes the printer's sequence envelope; it never emits HP+.
struct BLEPacketCodec {
    enum Failure: Error, CustomStringConvertible {
        case invalid(String)
        var description: String { switch self { case .invalid(let reason): return reason } }
    }
    private var expected = 1
    private var bytes: [UInt8] = []

    static func fragments(_ message: [UInt8], packetLimit: Int) throws -> [[UInt8]] {
        guard !message.isEmpty, message.count <= 4096, (2...4097).contains(packetLimit) else {
            throw Failure.invalid("Invalid BLE message or packet limit")
        }
        let payloadLimit = packetLimit - 1
        let count = (message.count + payloadLimit - 1) / payloadLimit
        guard count <= 127 else { throw Failure.invalid("BLE sequence space exceeded") }
        return (0..<count).map { index in
            let start = index * payloadLimit, end = min(start + payloadLimit, message.count)
            return [UInt8(index + 1) | (index + 1 == count ? 0x80 : 0)] + message[start..<end]
        }
    }

    mutating func receive(_ packet: [UInt8], ackPeriod: Int, packetLimit: Int) throws -> (message: [UInt8]?, acknowledge: Bool) {
        guard (0...127).contains(ackPeriod), (2...4097).contains(packetLimit),
              packet.count >= 2, packet.count <= packetLimit else {
            throw Failure.invalid("Invalid BLE notification length or unexpected ACK")
        }
        let sequence = Int(packet[0] & 0x7f), final = packet[0] & 0x80 != 0
        guard sequence == expected, sequence > 0, final || sequence < 127,
              bytes.count + packet.count - 1 <= 4096 else {
            throw Failure.invalid("BLE sequence or message bound mismatch")
        }
        bytes += packet.dropFirst()
        if final {
            let result = bytes
            bytes.removeAll(keepingCapacity: true); expected = 1
            return (result, false)
        }
        expected += 1
        return (nil, ackPeriod > 0 && sequence % ackPeriod == 0)
    }
}

struct BLECheckStatus: Equatable {
    let flags: UInt32
    let state: Int
    let battery: Int
    let progress: Int
    let currentJob: Int
    let power: Int
    let queue: Int
    let hosts: Int
    var summary: String {
        "battery \(battery)%, power \(power), state \(state), flags \(String(format: "0x%08X", flags)), current job \(currentJob), queue \(queue), hosts \(hosts)"
    }
}

struct BLECheckCapabilities {
    let version: Int?
    let protocolVersion: Int?
    let requests: [Int]
    let mime: [Int]
    let interfaces: [Int]
    let byteCount: Int
}

struct BLECheckResult {
    let firmware: String
    let model: Int
    let maximumMessage: Int
    let securityRaw: Int
    let protocolMTU: Int
    let acknowledgementPeriod: Int
    let before: BLECheckStatus
    let after: BLECheckStatus
    let capabilities: BLECheckCapabilities
    var summary: String {
        "BLE read-only check passed: firmware \(firmware), Select model 0x48D3; message maximum \(maximumMessage), security byte \(securityRaw), protocol MTU \(protocolMTU), ACK period \(acknowledgementPeriod). " +
        "Before: \(before.summary). After: \(after.summary). Capability table \(capabilities.byteCount) bytes; requests \(capabilities.requests.map(String.init).joined(separator: ",")). " +
        "No job allocated, image uploaded, print authorized, clock updated or persistent setting changed. This does not establish BLE print acceptance or throughput."
    }
}

/// Fixed read-only protocol experiment, deliberately independent of submission.
/// Only nextWrite() can produce application output; no caller-supplied opcode API.
/// A write-with-response callback is required before another write is offered.
struct BLEReadOnlyCheck {
    enum Failure: Error, CustomStringConvertible {
        case invalid(String), timeout, stopped
        var description: String {
            switch self {
            case .invalid(let text): return text
            case .timeout: return "BLE check deadline exceeded; no retry"
            case .stopped: return "BLE check stopped; no retry"
            }
        }
    }
    private enum Stage: String {
        case configure, firmware, model, setup, statusBefore, feature, download, statusAfter, done
    }
    private enum WriteKind { case request, acknowledgement }
    private var stage: Stage = .configure
    private var request: [UInt8] = []
    private var output: [[UInt8]] = []
    private var outputIndex = 0
    private var inFlight: WriteKind?
    private var ackQueue = 0
    private var response: [UInt8]?
    private var receiver = BLEPacketCodec()
    private var handle: UInt8?
    private var encoding: UInt8 = 0
    private var table: [UInt8] = []
    private var chunks = 0
    private var previousRemaining: Int?
    private var firmwareValue = ""
    private var maximumValue = 0
    private var securityValue = 0
    private var beforeValue: BLECheckStatus?
    private var afterValue: BLECheckStatus?
    private var capabilityValue: BLECheckCapabilities?
    private var protocolMTU = 20
    private var ackPeriod = 0
    private let platformWriteLimit: Int
    private let overallDeadline: TimeInterval
    private var exchangeDeadline: TimeInterval
    private var lastTime: TimeInterval
    private(set) var complete = false
    private(set) var failed = false
    private(set) var txBytes = 0
    private(set) var rxBytes = 0
    private(set) var requestCount = 0
    private(set) var result: BLECheckResult?
    var phase: String { stage.rawValue }
    var summary: String { result?.summary ?? "BLE read-only check \(failed ? "stopped" : "in progress") at \(phase); TX \(txBytes), RX \(rxBytes) application bytes, \(requestCount) fixed requests." }

    init(platformWriteLimit: Int, now: TimeInterval) throws {
        guard (20...65536).contains(platformWriteLimit), now.isFinite else {
            throw Failure.invalid("Invalid platform write limit or time")
        }
        self.platformWriteLimit = platformWriteLimit
        overallDeadline = now + 60; exchangeDeadline = now + 10; lastTime = now
        try prepare(now: now)
    }

    mutating func stop() {
        // Native cleanup and already-enqueued callbacks may arrive after success.
        // A successful terminal result cannot become both complete and failed.
        guard !complete else { return }
        failed = true; output.removeAll(); ackQueue = 0; response = nil; handle = nil
    }

    mutating func check(now: TimeInterval) throws {
        if complete { return }
        guard !failed else { throw Failure.stopped }
        guard now.isFinite, now >= lastTime else { stop(); throw Failure.invalid("Invalid or reversed monotonic time") }
        lastTime = now
        guard now < overallDeadline, now < exchangeDeadline else { stop(); throw Failure.timeout }
    }

    mutating func nextWrite(now: TimeInterval) throws -> [UInt8]? {
        try check(now: now)
        guard !complete, inFlight == nil else { return nil }
        let packet: [UInt8]
        if ackQueue > 0 {
            ackQueue -= 1; inFlight = .acknowledgement; packet = [0]
        } else if outputIndex < output.count {
            packet = output[outputIndex]; outputIndex += 1; inFlight = .request
        } else { return nil }
        txBytes += packet.count
        guard txBytes <= 16384 else { stop(); throw Failure.invalid("BLE transmit bound exceeded") }
        return packet
    }

    mutating func didWrite(now: TimeInterval) throws {
        if complete { return }
        try check(now: now)
        guard inFlight != nil else { stop(); throw Failure.invalid("Unexpected BLE write completion") }
        inFlight = nil
        do { try advanceIfReady(now: now) } catch { stop(); throw error }
    }

    /// Pass errors from native writes/disconnects to stop(); never retry a packet.
    mutating func receive(_ packet: [UInt8], now: TimeInterval) throws {
        if complete { return }
        try check(now: now)
        do {
            guard !complete, response == nil, outputIndex == output.count else {
                throw Failure.invalid("Unexpected or premature BLE response")
            }
            rxBytes += packet.count
            guard rxBytes <= 262144 else { throw Failure.invalid("BLE receive bound exceeded") }
            let event = try receiver.receive(packet, ackPeriod: ackPeriod, packetLimit: protocolMTU)
            if event.acknowledge {
                ackQueue += 1
                guard ackQueue <= 127 else { throw Failure.invalid("BLE acknowledgement bound exceeded") }
            }
            if let message = event.message { response = message }
            // A notification may precede the native write callback. Hold it until
            // that callback and any already-required acknowledgement finish.
            try advanceIfReady(now: now)
        } catch { stop(); throw error }
    }

    private func number(_ bytes: ArraySlice<UInt8>) -> Int {
        bytes.enumerated().reduce(0) { $0 | (Int($1.element) << (8 * $1.offset)) }
    }
    private func require(_ condition: Bool, _ text: String) throws {
        if !condition { throw Failure.invalid(text) }
    }
    private func variable(_ data: [UInt8], offset: inout Int) throws -> Int {
        var result = 0
        for shift in 0..<5 {
            try require(offset < data.count, "Truncated variable integer")
            let b = data[offset]; offset += 1; result |= Int(b & 127) << (shift * 7)
            if b < 128 { return result }
        }
        throw Failure.invalid("Variable integer exceeds bound")
    }
    private mutating func prepare(now: TimeInterval) throws {
        guard !failed, !complete, inFlight == nil else { throw Failure.stopped }
        switch stage {
        case .configure: request = [10,1,0]
        case .firmware: request = [4,1]
        case .model: request = [4,9]
        case .setup: request = [36,0,16]
        case .statusBefore, .statusAfter: request = [8,1,2,3,4,5,6,7,9]
        case .feature: request = [42]
        case .download:
            guard let handle else { throw Failure.invalid("No capability read handle") }
            request = [40,handle,1]
        case .done: throw Failure.invalid("Finished BLE experiment")
        }
        requestCount += 1
        try require(requestCount <= 72, "Read-only request bound exceeded")
        output = try BLEPacketCodec.fragments(request, packetLimit: min(protocolMTU, platformWriteLimit))
        outputIndex = 0; response = nil; exchangeDeadline = now + 10
    }
    private mutating func advanceIfReady(now: TimeInterval) throws {
        guard inFlight == nil, ackQueue == 0, let reply = response else { return }
        try require(!reply.isEmpty, "Empty BLE response")
        if reply[0] == 1 { throw Failure.invalid("Printer rejected read-only request at \(phase)") }
        try require(reply[0] == request[0] + 1, "Unexpected BLE response opcode at \(phase)")
        switch stage {
        case .configure:
            try require(reply.count == 5 && reply[1] == 1, "Malformed BLE IF_CONFIG response")
            protocolMTU = number(reply[2...3]); ackPeriod = Int(reply[4])
            try require((20...4097).contains(protocolMTU) && ackPeriod <= 127, "Invalid BLE MTU/ACK period")
            stage = .firmware
        case .firmware:
            try require(reply.count >= 3 && reply[1] == 1, "Malformed firmware response")
            var p = 2; let count = try variable(reply, offset: &p)
            try require(count > 0 && count <= 128 && p + count == reply.count, "Malformed firmware length")
            var raw = Array(reply[p...]); while raw.last == 0 { raw.removeLast() }
            try require(!raw.isEmpty && raw.allSatisfy { (32...126).contains($0) }, "Invalid firmware text")
            firmwareValue = String(decoding: raw, as: UTF8.self); stage = .model
        case .model:
            try require(reply == [5,9,211,72], "Device is not a Select (0x48D3)")
            stage = .setup
        case .setup:
            try require(reply.count == 4, "Malformed connection setup response")
            maximumValue = number(reply[1...2]); securityValue = Int(reply[3])
            try require((16...4096).contains(maximumValue), "Unsafe connection message maximum")
            // Preserve, report, and do not elevate or reinterpret security levels.
            stage = .statusBefore
        case .statusBefore:
            beforeValue = try status(reply); stage = .feature
        case .feature:
            try require(reply.count == 3 && [1,2].contains(reply[2]), "Malformed capability discovery")
            handle = reply[1]; encoding = reply[2]; stage = .download
        case .download:
            try require(reply.count >= 6 && reply[1] == handle, "Capability response handle mismatch")
            let remaining = number(reply[2...5]), amount = reply.count - 6
            chunks += 1
            try require(chunks <= 64 && table.count + amount + remaining <= 65536, "Capability table bound exceeded")
            if let previousRemaining { try require(previousRemaining == amount + remaining, "Capability remaining-length mismatch") }
            try require(remaining == 0 || amount > 0, "Capability download made no progress")
            previousRemaining = remaining; table += reply.dropFirst(6)
            if remaining == 0 {
                capabilityValue = try capabilities(table, encoding: encoding)
                handle = nil; stage = .statusAfter
            }
        case .statusAfter:
            afterValue = try status(reply)
            guard let beforeValue, let afterValue, let capabilityValue else { throw Failure.invalid("Incomplete BLE check") }
            result = BLECheckResult(firmware: firmwareValue, model: 0x48d3, maximumMessage: maximumValue,
                securityRaw: securityValue, protocolMTU: protocolMTU, acknowledgementPeriod: ackPeriod,
                before: beforeValue, after: afterValue, capabilities: capabilityValue)
            stage = .done; complete = true; response = nil; output.removeAll(); return
        case .done: throw Failure.invalid("Unexpected response after completion")
        }
        try prepare(now: now)
    }
    private func status(_ bytes: [UInt8]) throws -> BLECheckStatus {
        let widths: [UInt8:Int] = [1:4,2:1,3:1,4:1,5:2,6:1,7:1,9:1]
        var p = 1, fields: [UInt8:Int] = [:]
        while p < bytes.count {
            let tag = bytes[p]; p += 1
            guard let width = widths[tag], fields[tag] == nil, p + width <= bytes.count else {
                throw Failure.invalid("Unknown, duplicate or truncated status field")
            }
            fields[tag] = number(bytes[p..<p+width]); p += width
        }
        try require(fields.count == widths.count && (0...100).contains(fields[3] ?? -1) && (0...100).contains(fields[4] ?? -1), "Missing or invalid status fields")
        return BLECheckStatus(flags: UInt32(fields[1]!), state: fields[2]!, battery: fields[3]!,
            progress: fields[4]!, currentJob: fields[5]!, power: fields[6]!, queue: fields[7]!, hosts: fields[9]!)
    }
    private func capabilities(_ data: [UInt8], encoding: UInt8) throws -> BLECheckCapabilities {
        var values: [Int:[Int]] = [:]
        if encoding == 1 {
            struct Features: Decodable {
                let version: Int?
                let proto_version: Int?
                let requests: [Int]
                let mime: [Int]
                let ifs: [Int]
            }
            let feature = try JSONDecoder().decode(Features.self, from: Data(data))
            values[1] = feature.version.map { [$0] }; values[2] = feature.proto_version.map { [$0] }
            values[3] = feature.requests; values[7] = feature.mime; values[11] = feature.ifs
        } else {
            var p = 0, seen = Set<Int>()
            while p < data.count {
                try require(p + 3 <= data.count, "Truncated capability TLV")
                let tag = Int(data[p]), length = number(data[p+1...p+2]); p += 3
                try require(p + length <= data.count && seen.insert(tag).inserted, "Invalid capability TLV length/duplicate")
                let raw = Array(data[p..<p+length]); p += length
                if [1,2].contains(tag) {
                    try require(raw.count == 2, "Invalid scalar capability width"); values[tag] = [number(raw[...])]
                } else if [3,7,11].contains(tag) {
                    var start = 0; let count = try variable(raw, offset: &start)
                    try require(start + count == raw.count, "Invalid capability array length")
                    values[tag] = raw.dropFirst(start).map(Int.init)
                }
            }
        }
        guard let requests = values[3], let mime = values[7], let interfaces = values[11] else {
            throw Failure.invalid("Capability table missing requests, MIME or interfaces")
        }
        for array in [requests,mime,interfaces] {
            try require(array.count <= 256 && array.allSatisfy { (0...255).contains($0) } && Set(array).count == array.count, "Invalid capability values")
        }
        return BLECheckCapabilities(version: values[1]?.first, protocolVersion: values[2]?.first,
            requests: requests, mime: mime, interfaces: interfaces, byteCount: data.count)
    }
}
