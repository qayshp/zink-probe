import Foundation

let expectedDevice = String(repeating: "07", count: 16)
let expectedFirmware = "G1L1FA2105AR"
let expectedUpdate: [UInt8] = [24,0,241,83,101,144,157,255,255]
let expectedRequests: [[UInt8]] = [[10,1,0], [4,1], [4,9], [4,6], [36,0,16], [26,4], [8,1,2,3,5,6,7], [44], expectedUpdate, [8,1]]
let clockIndex = expectedRequests.count - 2

/// Deterministic packet peer for the clock protocol. It records each complete
/// request so the tests can prove exactly which writes the printer would see.
final class ClockPeer: BLEPacketIO {
    var flags: UInt8 = 1
    var state: UInt8 = 1, currentJob: UInt8 = 0, queueState: UInt8 = 1, battery: UInt8 = 72, power: UInt8 = 1
    var queued: UInt8 = 0
    var paused = false
    var firmware = expectedFirmware
    var device: UInt8 = 7, model: UInt8 = 211
    var setupReply: [UInt8] = [37,232,3,33]
    var disconnectedAt: [UInt8]?, refusedAt: [UInt8]?, droppedReply: [UInt8]?
    var clockReply: [UInt8] = [25]
    var afterwards: [UInt8] = [9,1,0,0,0,0]
    var inline = false, notificationFirst = false
    private var handler: ((BLEPacketIOEvent) -> Void)?
    private var lateHandler: ((BLEPacketIOEvent) -> Void)?
    private var events = [BLEPacketIOEvent]()
    private var pending = BLEPacketCodec()
    private(set) var writes = [[UInt8]]()
    private(set) var closes = 0

    func open(_ handler: @escaping (BLEPacketIOEvent) -> Void) {
        self.handler = handler; lateHandler = handler
        enqueue([.ready(writeLimit: 20)])
    }

    func write(_ packet: [UInt8]) -> Bool {
        guard handler != nil else { return false }
        precondition(packet.dropFirst().prefix(3) != [72,80,43], "HP+ framing crossed GATT")
        let event = try! pending.receive(packet, ackPeriod: 0, packetLimit: 20)
        guard let payload = event.message else { enqueue([.written]); return true }
        guard payload != refusedAt else { return false }
        writes.append(payload)
        if payload == disconnectedAt { enqueue([.ended]); return true }
        if payload == droppedReply { enqueue([.written]); return true }
        let reply: [UInt8]
        switch payload {
        case [10,1,0]: reply = [11,1,20,0,0]
        case [4,1]: reply = [5,1,UInt8(firmware.utf8.count)] + Array(firmware.utf8)
        case [4,9]: reply = [5,9,model,72]
        case [4,6]: reply = [5,6] + Array(repeating: device, count: 16)
        case [36,0,16]: reply = setupReply
        case [26,4]: reply = [27,4,paused ? 1 : 0]
        case [8,1,2,3,5,6,7]: reply = [9,1,flags,0,0,0,2,state,3,battery,5,currentJob,0,6,power,7,queueState]
        case [44]: reply = queued == 0 ? [45] : [45,queued,0]
        case expectedUpdate: reply = clockReply
        case [8,1]: reply = afterwards
        default: fatalError("Unexpected clock exchange packet: \(payload)")
        }
        let response = try! BLEPacketCodec.fragments(reply, packetLimit: 20).map { BLEPacketIOEvent.notification($0) }
        enqueue(notificationFirst ? response + [.written] : [.written] + response)
        return true
    }

    private func enqueue(_ work: [BLEPacketIOEvent]) {
        if inline { work.forEach { handler?($0) } }
        else { events += work }
    }
    func nextEvent() { if !events.isEmpty { handler?(events.removeFirst()) } }
    func lateEnd() { lateHandler?(.ended) }
    func close() { closes += 1; handler = nil; events.removeAll() }
}

final class Trial {
    private(set) var results = [BLEClockSession.Outcome]()
    var now = 0.0
    let peer: ClockPeer
    private(set) var session: BLEClockSession!

    init(_ peer: ClockPeer, firmware: String = expectedFirmware,
         date: Date = Date(timeIntervalSince1970: 1700000000)) throws {
        self.peer = peer
        session = try BLEClockSession(io: peer, expectedDeviceID: expectedDevice, expectedFirmware: firmware,
            clock: { [unowned self] in now }, wallClock: { date },
            timeZone: { TimeZone(secondsFromGMT: -25200)! },
            update: { [unowned self] in results.append($0) })
    }

    @discardableResult func run() -> BLEClockSession.Outcome {
        session.start()
        for _ in 0..<2_000 {
            if session.closed { break }
            now += 0.02
            peer.nextEvent(); session.tick()
        }
        precondition(session.closed && peer.closes == 1 && results.count == 1)
        peer.lateEnd(); session.start(); session.tick(); session.cancel("Late cancellation.")
        precondition(peer.closes == 1 && results.count == 1)
        return results[0]
    }
}

for inline in [false,true] {
    for notificationFirst in [false,true] {
        let peer = ClockPeer(); peer.inline = inline; peer.notificationFirst = notificationFirst
        peer.firmware += "-longer-to-fragment"
        let outcome = try Trial(peer, firmware: peer.firmware).run()
        precondition(outcome == .verified)
        precondition(peer.writes == expectedRequests)
    }
}

do {
    let peer = ClockPeer(); peer.flags = 0
    let outcome = try Trial(peer).run()
    precondition(outcome == .notNeeded)
    precondition(peer.writes == Array(expectedRequests.prefix(clockIndex - 1)))
}

let blockers: [(ClockPeer) -> Void] = [
    { $0.firmware = "different" }, { $0.device = 8 }, { $0.model = 0 },
    { $0.setupReply = [37,232,3,99] }, { $0.paused = true },
    { $0.flags = 3 }, { $0.state = 7 }, { $0.currentJob = 2 }, { $0.queueState = 4 },
    { $0.battery = 29 }, { $0.power = 0 }, { $0.queued = 7 }
]
for block in blockers {
    let peer = ClockPeer(); block(peer)
    guard case .refused = try Trial(peer).run() else { fatalError("Expected pre-write refusal") }
    precondition(!peer.writes.contains(expectedUpdate))
}

for boundary in expectedRequests.indices {
    let peer = ClockPeer(); peer.disconnectedAt = expectedRequests[boundary]
    let result = try Trial(peer).run()
    switch (boundary, result) {
    case (0..<clockIndex, .refused), (clockIndex, .possiblyWritten), (clockIndex + 1, .acknowledgedUnverified): break
    default: fatalError("Unexpected result at disconnect boundary \(boundary): \(result)")
    }
    precondition(peer.writes == Array(expectedRequests.prefix(boundary + 1)))
}

for drop in [expectedUpdate, [8,1]] {
    let peer = ClockPeer(); peer.droppedReply = drop
    switch (drop, try Trial(peer).run()) {
    case (expectedUpdate, .possiblyWritten), ([8,1], .acknowledgedUnverified): break
    default: fatalError("Expected ambiguous clock timeout")
    }
    precondition(peer.writes.filter { $0 == expectedUpdate }.count == 1)
}

do {
    let peer = ClockPeer(); peer.refusedAt = expectedUpdate; peer.inline = true
    guard case .possiblyWritten = try Trial(peer).run() else { fatalError("Expected conservative write refusal") }
    precondition(peer.writes == Array(expectedRequests.prefix(clockIndex)))
}

do {
    let peer = ClockPeer(); peer.clockReply = [1,24,7]
    guard case .possiblyWritten = try Trial(peer).run() else { fatalError("Expected missing clock acknowledgement") }
    precondition(peer.writes == Array(expectedRequests.prefix(clockIndex + 1)))
}

for flags: UInt8 in [1,2] {
    let peer = ClockPeer(); peer.afterwards = [9,1,flags,0,0,0]
    guard case .acknowledgedUnverified = try Trial(peer).run() else { fatalError("Expected verification refusal") }
    precondition(peer.writes == expectedRequests)
}

do {
    let peer = ClockPeer()
    guard case .refused = try Trial(peer, date: Date(timeIntervalSince1970: -1)).run() else { fatalError("Expected out-of-range time refusal") }
    precondition(peer.writes == Array(expectedRequests.prefix(clockIndex)))
}

do {
    let peer = ClockPeer()
    let trial = try Trial(peer)
    trial.session.start()
    for _ in 0..<100 {
        if peer.writes.contains(expectedUpdate) { break }
        peer.nextEvent(); trial.session.tick()
    }
    precondition(peer.writes.contains(expectedUpdate))
    trial.session.cancel("Stopped by user.")
    guard case .possiblyWritten = trial.run() else { fatalError("Expected an explicit stop after the write started") }
    precondition(peer.writes == Array(expectedRequests.prefix(clockIndex + 1)))
}

/// Exercise the transport allowlists independently of the orchestrated session.
let forbidden: [(BLESubmissionDuplex.Policy, [UInt8])] = [
    (.readOnly, expectedUpdate), (.singleJobSubmission, expectedUpdate),
    (.clockSync(BLEClockWriteAuthorization()), expectedUpdate),
    (.clockSync(BLEClockWriteAuthorization()), [12,1,0,0,0,0]),
    (.clockSync(BLEClockWriteAuthorization()), [14,1,2,3,4]),
    (.clockSync(BLEClockWriteAuthorization()), [48,1,2]),
    (.clockSync(BLEClockWriteAuthorization()), [36,0,32])
]
for (policy, payload) in forbidden {
    let peer = ClockPeer(); peer.inline = true
    let duplex = BLESubmissionDuplex(io: peer, clock: { 0 }, policy: policy)
    duplex.open { _ in }
    precondition(duplex.hasSpace)
    let frame = [72,80,43,1,UInt8(payload.count)] + payload
    precondition(duplex.write(frame) < 0 && duplex.closed && peer.writes == [[10,1,0]])
}

print("BLE clock checks passed: exact timestamp and time zone, identity, pause, queue and power gates, no-op, interruptions, timeout, cancellation, and isolated output policies.")
