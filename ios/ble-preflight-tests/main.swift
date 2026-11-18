import Foundation

private var checks = 0
func check(_ condition: Bool, _ reason: String = "check failed", file: StaticString = #file, line: UInt = #line) {
    checks += 1
    precondition(condition, reason, file: file, line: line)
}
final class Clock { var now = 0.0 }

/// Independent packet fixture: decode requests here, not with the production
/// codec. Only payload responses come from the existing deterministic peer.
final class PreflightPeer: BLEPacketIO {
    let printer = SimulatedPrinter()
    let mtu: Int, ack: Int, nativeLimit: Int
    var earlyNotification = false
    var noReady = false
    var dropOpcode: UInt8?
    var corruptOpcode: UInt8?
    var duplicateOpcode: UInt8?
    var responseOverrides: [UInt8:[UInt8]] = [:]
    var disconnectAt: Int?
    private(set) var packets: [[UInt8]] = []
    private(set) var requests: [[UInt8]] = []
    private(set) var opens = 0, closes = 0
    private var closed = false, outstanding = false
    private var callback: ((BLEPacketIOEvent) -> Void)?
    private var savedCallback: ((BLEPacketIOEvent) -> Void)?
    private var events: [BLEPacketIOEvent] = []
    private var replyPackets: [[UInt8]] = []
    private var assembly: [UInt8] = [], sequence = 1
    init(mtu: Int = 514, ack: Int = 0, nativeLimit: Int = 512) {
        self.mtu = mtu; self.ack = ack; self.nativeLimit = nativeLimit
    }
    func open(_ handler: @escaping (BLEPacketIOEvent) -> Void) {
        opens += 1; callback = handler; savedCallback = handler
        if !noReady { events = [.ready(writeLimit:nativeLimit)] }
    }
    func write(_ packet: [UInt8]) -> Bool {
        check(!closed && !outstanding, "No overlapping native writes")
        check(!packet.isEmpty && packet.count <= nativeLimit, "Platform packet maximum")
        packets.append(packet); outstanding = true
        if packet != [0] {
            check(packet.count >= 2 && Int(packet[0] & 127) == sequence, "Ordered request fragments")
            if sequence == 1 { check(Array(packet.dropFirst().prefix(3)) != [72,80,43], "HP+ is internal only") }
            assembly += packet.dropFirst(); sequence += 1
            if packet[0] & 128 != 0 {
                let request = assembly; assembly = []; sequence = 1; requests.append(request)
                check(request == [10,1,0] || ReadOnlyFrameGate.allows(request), "Only read-only requests")
                if request.first != dropOpcode {
                    var response: [UInt8]
                    if request == [10,1,0] { response = [11,1,UInt8(mtu & 255),UInt8(mtu >> 8),UInt8(ack)] }
                    else {
                        response = responseOverrides[request[0]] ?? printer.respond(request)
                        if request.first == 40 { response += [99,200,0] + [UInt8](repeating:0,count:200) }
                    }
                    replyPackets = stride(from:0,to:response.count,by:mtu-1).enumerated().map { index, start in
                        let end = min(start+mtu-1,response.count)
                        return [UInt8(index+1) | (end == response.count ? 128 : 0)] + response[start..<end]
                    }
                    if request.first == corruptOpcode { replyPackets[0][0] = 0x82 }
                    if request.first == duplicateOpcode { replyPackets.insert(replyPackets[0],at:1) }
                }
            }
        }
        if earlyNotification { releaseReplies(); events.append(.written) }
        else { events.append(.written); releaseReplies() }
        if packets.count-1 == disconnectAt { events = [.ended]; replyPackets = [] }
        return true
    }
    private func releaseReplies() {
        while !replyPackets.isEmpty {
            let packet = replyPackets.removeFirst(); events.append(.notification(packet))
            if packet[0] & 128 == 0 && ack > 0 && Int(packet[0] & 127) % ack == 0 { break }
        }
    }
    func step() {
        guard !closed, !events.isEmpty else { return }
        let event = events.removeFirst()
        if case .written = event { check(outstanding); outstanding = false }
        callback?(event)
    }
    func inject(_ event: BLEPacketIOEvent) { callback?(event) }
    func late(_ event: BLEPacketIOEvent) { savedCallback?(event) }
    func close() { closes += 1; closed = true; callback = nil; events = []; replyPackets = [] }
}

final class Run {
    let clock: Clock, peer: PreflightPeer, session: BLECoordinatorSession
    init(peer: PreflightPeer = PreflightPeer(), expectedID: String? = nil, expectedFirmware: String = "G1L1FA2105AR") throws {
        let clock = Clock(); self.clock = clock; self.peer = peer
        session = try BLECoordinatorSession.preflight(io:peer,expectedDeviceID:expectedID,
            expectedFirmware:expectedFirmware,clock:{ clock.now },update:{ _ in })
    }
    func step() { clock.now += 0.01; peer.step(); session.tick() }
    func finish() {
        session.start()
        for _ in 0..<20000 { if session.closed { return }; step() }
        fatalError("Read-only preflight did not terminate")
    }
    func assertReadOnly() {
        check(peer.requests.allSatisfy { $0 == [10,1,0] || ReadOnlyFrameGate.allows($0) })
        check(!peer.requests.contains { [UInt8(12),14,48,24,22,16].contains($0.first ?? 0) }, "No allocation, image, print, clock or settings")
        check(session.pump.totalImageBytes == 0 && session.pump.acknowledgedImageBytes == 0)
        check(session.pump.jobState == nil)
        check(peer.opens == 1 && peer.closes == 1)
    }
}

var normalPacketCount = 0
for mtu in [20,514] {
    for period in [0,1,7] {
        for early in [false,true] {
            let peer = PreflightPeer(mtu:mtu,ack:period,nativeLimit:mtu == 20 ? 20 : 512)
            peer.earlyNotification = early
            let run = try Run(peer:peer,expectedID:peer.printer.device)
            // Constructing a screen/session must not create/open a native IO.
            check(peer.opens == 0 && peer.packets.isEmpty)
            run.finish(); run.assertReadOnly()
            check(run.session.pump.succeeded && run.session.pump.streamsOpened == 2)
            check(run.session.pump.verified?.deviceID == peer.printer.device)
            check(run.session.pump.result.contains("pages 13, calibration cycles 2"))
            check(!run.session.pump.result.contains(peer.printer.device), "Report omits canonical identity")
            check(peer.requests.map { $0[0] } == [10,4,4,4,36,42,40,26,8,44,58])
            if mtu == 514 && period == 0 && !early { normalPacketCount = peer.packets.count }
        }
    }
}

for fault in ["clock-invalid","paused","wrong-identity","wrong-firmware","sequence","duplicate","lost-status"] {
    let peer = PreflightPeer(mtu:20,ack:1,nativeLimit:20)
    if fault == "clock-invalid" { peer.printer.initialFlags = 1 }
    if fault == "paused" { peer.printer.paused = true }
    if fault == "wrong-identity" { peer.printer.mismatchIdentity = true }
    if fault == "sequence" { peer.corruptOpcode = 4 }
    if fault == "duplicate" { peer.duplicateOpcode = 4 }
    if fault == "lost-status" { peer.dropOpcode = 8 }
    let run = try Run(peer:peer,expectedID:peer.printer.device,expectedFirmware:fault == "wrong-firmware" ? "wrong" : peer.printer.firmware)
    run.finish(); run.assertReadOnly()
    check(!run.session.pump.succeeded && run.session.pump.verified == nil,"Fault \(fault) must not create readiness evidence")
    check(!run.session.pump.result.contains(peer.printer.device))
    if fault == "clock-invalid" {
        check(run.session.pump.result.contains("0x00000001"))
        check(run.session.pump.result.contains("Printer not idle/empty/error-free"))
        check(!peer.requests.contains { $0.first == 44 || $0.first == 58 }, "Strict readiness refuses before remaining reads")
        check(peer.printer.initialFlags == 1, "No clock repair")
    }
    let count = peer.packets.count
    peer.late(.written); peer.late(.notification([0x81,9])); run.session.tick()
    check(peer.packets.count == count && peer.closes == 1)
}

check(normalPacketCount > 0)
for cut in 0..<normalPacketCount {
    for fault in ["disconnect","dismiss","background"] {
        let peer = PreflightPeer()
        if fault == "disconnect" { peer.disconnectAt = cut }
        let run = try Run(peer:peer)
        run.session.start(); run.session.start() // A repeated tap cannot reopen.
        if fault != "disconnect" {
            while !run.session.closed && peer.packets.count <= cut { run.step() }
            run.session.cancel(fault == "dismiss" ? "BLE screen closed" : "Share host entered the background")
        }
        run.finish(); run.assertReadOnly()
        check(!run.session.pump.succeeded && run.session.pump.verified == nil)
        let count = peer.packets.count
        run.session.cancel("Repeated stop"); peer.late(.ready(writeLimit:512)); peer.late(.written); run.session.tick()
        check(peer.packets.count == count && peer.closes == 1)
    }
}

for delay in [15.0,90.0] {
    let peer = PreflightPeer(); peer.noReady = true
    let run = try Run(peer:peer); run.session.start()
    run.clock.now = delay; run.session.tick(); peer.inject(.ready(writeLimit:512)); run.finish()
    run.assertReadOnly(); check(run.session.pump.succeeded == (delay < 90))
}

do {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at:directory,withIntermediateDirectories:true)
    defer { try? FileManager.default.removeItem(at:directory) }
    let journal = try JobJournal(url:directory.appendingPathComponent("disabled.sqlite"))
    let id = UUID(), adapter = NativeBLEAdapter()
    let binding = JobBinding(id:id,device:String(repeating:"07",count:16),firmware:"G1L1FA2105AR",
        digest:String(repeating:"0",count:64),byteCount:100,sampling:"4:4:4",
        settings:.init(layout:"Fit",quality:100),checkedAt:Date(timeIntervalSince1970:0),schema:1)
    var updated = false
    do {
        try adapter.submitOnce(peripheralID:UUID(),reviewed:binding,journal:journal,update:{ _ in updated = true })
        fatalError("Native BLE submission must remain disabled")
    } catch BLESubmissionAvailability.Failure.liveSubmissionDisabled { checks += 1 }
    check(!adapter.active && !updated)
    check(try journal.attemptState(id) == nil && journal.record(id) == nil)
}

// Exercise the production UI controller with a narrow fake adapter. Nothing in
// this interface can request printing, recovery, clock or settings writes.
final class FakePreflightAdapter: BLEPreflightAdapter {
    struct Start { let peripheral: UUID; let device: String?; let firmware: String }
    var active = false
    var starts: [Start] = [], callbacks: [(AccessoryStreamPump) -> Void] = []
    var stops: [String] = []
    var startError: Error?
    var activateBeforeThrow = false
    var whenStopping: (() -> Void)?
    var failureStage: BLESubmissionDuplex.FailureStage?
    var transportSummary: String { "BLE GATT packets: queued=40, acknowledged=40, callbacks=8, RX=314." }
    func preflight(peripheralID: UUID, expectedDeviceID: String?, expectedFirmware: String,
                   update: @escaping (AccessoryStreamPump) -> Void) throws {
        if let startError {
            if activateBeforeThrow { active = true; callbacks.append(update) }
            throw startError
        }
        active = true; starts.append(.init(peripheral:peripheralID,device:expectedDeviceID,firmware:expectedFirmware)); callbacks.append(update)
    }
    func stop(_ reason: String) { active = false; stops.append(reason); whenStopping?() }
    func emit(_ pump: AccessoryStreamPump, at index: Int? = nil) {
        if pump.terminal { active = false }
        callbacks[index ?? callbacks.count-1](pump)
    }
}

// Assemble status replies independently of the production parser. A clock bit
// in an incomplete/malformed reply must never become a clock-sync instruction.
func statusReply(flags: UInt32 = 0, state: UInt8 = 1, currentJob: UInt16 = 0,
                 queue: UInt8 = 1, battery: UInt8 = 72, power: UInt8 = 1) -> [UInt8] {
    [9,1,UInt8(truncatingIfNeeded:flags),UInt8(truncatingIfNeeded:flags >> 8),
     UInt8(truncatingIfNeeded:flags >> 16),UInt8(truncatingIfNeeded:flags >> 24),
     2,state,3,battery,5,UInt8(truncatingIfNeeded:currentJob),UInt8(truncatingIfNeeded:currentJob >> 8),
     6,power,7,queue]
}

for fault in ["clock-only","clock-other-flags","clock-busy","clock-low-battery","clock-unknown-power","other-flags","paused","low-battery","queued-jobs","malformed-clock-status","clock-invalid-battery","unknown-pause"] {
    let peer = PreflightPeer()
    switch fault {
    case "clock-only": peer.responseOverrides[8] = statusReply(flags:1)
    case "clock-other-flags": peer.responseOverrides[8] = statusReply(flags:0x80000001)
    case "clock-busy": peer.responseOverrides[8] = statusReply(flags:1,state:7,currentJob:16,queue:4)
    case "clock-low-battery": peer.responseOverrides[8] = statusReply(flags:1,battery:12)
    case "clock-unknown-power": peer.responseOverrides[8] = statusReply(flags:1,power:3)
    case "other-flags": peer.responseOverrides[8] = statusReply(flags:4)
    case "paused": peer.printer.paused = true
    case "low-battery": peer.responseOverrides[8] = statusReply(battery:12)
    case "queued-jobs": peer.responseOverrides[44] = [45,16,0]
    case "clock-invalid-battery": peer.responseOverrides[8] = statusReply(flags:1,battery:101)
    case "unknown-pause": peer.responseOverrides[26] = [27,4,2]
    default: peer.responseOverrides[8] = [9,1,1,0,0,0]
    }
    let run = try Run(peer:peer); run.finish(); run.assertReadOnly()
    let pump = run.session.pump
    check(!pump.succeeded && pump.verified == nil && pump.streamsOpened == 2)
    check(run.session.duplex.failureStage == nil,"A valid transport with refused readiness is not a BLE transport failure")
    switch fault {
    case "clock-only": check(pump.readinessRefusal == .printerStatus(flags:1,state:1,currentJob:0,queue:1,battery:72,power:1))
    case "clock-other-flags": check(pump.readinessRefusal == .printerStatus(flags:0x80000001,state:1,currentJob:0,queue:1,battery:72,power:1))
    case "clock-busy": check(pump.readinessRefusal == .printerStatus(flags:1,state:7,currentJob:16,queue:4,battery:72,power:1))
    case "clock-low-battery": check(pump.readinessRefusal == .printerStatus(flags:1,state:1,currentJob:0,queue:1,battery:12,power:1))
    case "clock-unknown-power": check(pump.readinessRefusal == .printerStatus(flags:1,state:1,currentJob:0,queue:1,battery:72,power:3))
    case "other-flags": check(pump.readinessRefusal == .printerStatus(flags:4,state:1,currentJob:0,queue:1,battery:72,power:1))
    case "paused": check(pump.readinessRefusal == .paused)
    case "low-battery": check(pump.readinessRefusal == .batteryOrPower)
    case "queued-jobs": check(pump.readinessRefusal == .queuedJobs)
    default: check(pump.readinessRefusal == nil,"An incomplete clock-bearing reply is a protocol error, not readiness evidence")
    }
    let fake = FakePreflightAdapter()
    let controller = BLEPreflightController(context:"offline readiness \(fault)",adapter:fake)
    controller.run(peripheralID:UUID(),firmware:peer.printer.firmware)
    fake.emit(pump)
    check(!controller.active && !fake.active && fake.starts.count == 1)
    switch fault {
    case "clock-only":
        check(controller.status == "Printer connected; clock sync needed.")
        check(controller.lastResult.contains("Use the separate clock-sync action") && controller.lastResult.contains("then run this check again"))
    case "clock-other-flags","clock-busy","clock-low-battery","clock-unknown-power":
        check(controller.status == "Printer connected; clock sync and other checks need attention.")
        check(controller.lastResult.contains("Other status, queue, or battery/power conditions also prevent readiness."))
    case "malformed-clock-status","clock-invalid-battery","unknown-pause":
        check(controller.status == "BLE printer check did not complete.")
        check(!controller.lastResult.contains("Use the separate clock-sync action"),"Incomplete status must not recommend a clock fix")
    default:
        check(controller.status == "Printer connected; not ready.")
        check(!controller.lastResult.contains("Use the separate clock-sync action"))
    }
    check(!controller.report.contains(peer.printer.device))
    check(!peer.requests.contains { [UInt8(12),14,48,24,22,16].contains($0.first ?? 0) })
}

for fault in ["connection-failed","connection-deadline","setup-failed","exchange-disconnected","exchange-sequence"] {
    let peer = PreflightPeer()
    if fault.hasPrefix("connection") { peer.noReady = true }
    if fault == "setup-failed" { peer.corruptOpcode = 10 }
    if fault == "exchange-disconnected" { peer.disconnectAt = 1 }
    if fault == "exchange-sequence" { peer.corruptOpcode = 4 }
    let run = try Run(peer:peer)
    if fault.hasPrefix("connection") {
        run.session.start()
        if fault == "connection-failed" { peer.inject(.failed) }
        else { run.clock.now = 90; run.session.tick() }
    }
    run.finish(); run.assertReadOnly()
    let expected: BLESubmissionDuplex.FailureStage = fault.hasPrefix("connection") ? .connection : fault == "setup-failed" ? .setup : .exchange
    check(run.session.duplex.failureStage == expected)
    check(!run.session.pump.succeeded && run.session.pump.verified == nil && run.session.pump.readinessRefusal == nil)
    let fake = FakePreflightAdapter(); fake.failureStage = run.session.duplex.failureStage
    let routing = UUID(), controller = BLEPreflightController(context:"offline transport \(fault)",adapter:fake)
    controller.run(peripheralID:routing,firmware:peer.printer.firmware)
    fake.emit(run.session.pump)
    check(!controller.active && !fake.active && fake.starts.count == 1,"Failure must return control without automatic retry")
    switch expected {
    case .connection:
        check(controller.status == "BLE connection unavailable.")
        check(controller.lastResult.contains("A usable BLE connection to the selected printer could not be established."))
    case .setup: check(controller.status == "BLE setup did not complete.")
    case .exchange: check(controller.status == "BLE communication did not complete.")
    }
    check(!controller.lastResult.contains("Use the separate clock-sync action"))
    check(!controller.report.contains(routing.uuidString) && !controller.report.contains(peer.printer.device))
    if expected == .connection {
        check(run.session.pump.acceptedBytes == 0 && run.session.pump.receivedBytes == 0)
        check(peer.packets.isEmpty && run.session.pump.streamsOpened == 0)
        let successful = try Run(); successful.finish()
        fake.failureStage = nil
        controller.run(peripheralID:routing,firmware:peer.printer.firmware)
        check(controller.active && fake.starts.count == 2,"An explicit rerun is possible after unavailable failure")
        fake.emit(successful.session.pump)
        check(!controller.active && controller.status.contains("passed"))
    }
}

do {
    let successful = try Run(); successful.finish()
    let badPeer = PreflightPeer(); badPeer.printer.initialFlags = 1
    let refused = try Run(peer:badPeer); refused.finish()
    let fake = FakePreflightAdapter(), routingID = UUID(), otherID = UUID()
    let controller = BLEPreflightController(context:"offline controller",adapter:fake)
    check(fake.starts.isEmpty && fake.stops.isEmpty && !controller.active,"Constructing the screen must be passive")
    let original = controller.report
    controller.stop("Nothing to stop"); check(controller.report == original)
    for firmware in ["", "bad\nfirmware", String(repeating:"x",count:129)] {
        controller.run(peripheralID:routingID,firmware:firmware)
        check(fake.starts.isEmpty && !controller.active)
    }
    controller.run(peripheralID:routingID,firmware:"G1L1FA2105AR")
    check(fake.starts.count == 1 && controller.active)
    check(fake.starts[0].peripheral == routingID && fake.starts[0].device == nil && fake.starts[0].firmware == "G1L1FA2105AR")
    controller.run(peripheralID:otherID,firmware:"other")
    check(fake.starts.count == 1,"Repeated taps cannot replace an active selection")
    fake.emit(successful.session.pump)
    check(!controller.active && controller.status.contains("passed") && controller.lastResult == successful.session.pump.result)
    check(controller.report.contains(fake.transportSummary) && controller.report.contains("internal framing, not raw GATT traffic"))
    let terminalReport = controller.report
    fake.emit(refused.session.pump,at:0)
    check(controller.report == terminalReport,"A terminal operation cannot be changed by another callback")

    controller.run(peripheralID:otherID,firmware:"G1L1FA2105AR")
    check(fake.starts.count == 2 && fake.starts[1].peripheral == otherID)
    let activeReport = controller.report
    fake.callbacks[0](refused.session.pump)
    check(controller.active && controller.report == activeReport,"A stale generation cannot terminate the new operation")
    fake.emit(refused.session.pump)
    check(!controller.active && controller.status == "Printer connected; clock sync needed.")
    check(controller.report.contains(refused.session.pump.result) && controller.report.contains(controller.status))
    check(controller.report.contains("This check left the clock unchanged."))
    check(!controller.report.contains(routingID.uuidString) && !controller.report.contains(otherID.uuidString))
    check(!controller.report.contains(badPeer.printer.device),"Reports must not expose routing or protocol identities")

    for reason in ["BLE screen closed","Share host entered the background"] {
        controller.run(peripheralID:routingID,firmware:"G1L1FA2105AR")
        let callback = fake.callbacks.last!
        fake.whenStopping = { callback(successful.session.pump) }
        let stopCount = fake.stops.count
        controller.stop(reason)
        check(!controller.active && fake.stops.count == stopCount+1 && controller.lastResult == reason)
        check(controller.status.contains("stopped"),"Inline stop callback must not publish success")
        let stopped = controller.report
        callback(successful.session.pump); controller.stop(reason)
        check(controller.report == stopped && fake.stops.count == stopCount+1)
    }
    fake.whenStopping = nil
    fake.startError = NSError(domain:routingID.uuidString,code:9,userInfo:[NSLocalizedDescriptionKey:badPeer.printer.device])
    controller.run(peripheralID:routingID,firmware:"G1L1FA2105AR")
    check(!controller.active && controller.status.contains("could not start"))
    check(!controller.report.contains(routingID.uuidString) && !controller.report.contains(badPeer.printer.device),"Unknown start errors must be sanitized")
    fake.activateBeforeThrow = true
    fake.whenStopping = { fake.callbacks.last!(successful.session.pump) }
    let stops = fake.stops.count
    controller.run(peripheralID:routingID,firmware:"G1L1FA2105AR")
    check(!controller.active && !fake.active && fake.stops.count == stops+1)
    check(controller.status.contains("could not start"),"Partial-start cleanup invalidates callbacks before stopping native IO")
    check(!controller.report.contains(routingID.uuidString) && !controller.report.contains(badPeer.printer.device))
    fake.whenStopping = nil
}

do {
    let fake = FakePreflightAdapter(); fake.active = true
    let controller = BLEPreflightController(context:"busy adapter",adapter:fake)
    controller.run(peripheralID:UUID(),firmware:"G1L1FA2105AR")
    check(fake.starts.isEmpty && !controller.active,"An already active native adapter cannot be driven twice")
}
do {
    let fake = FakePreflightAdapter()
    final class WeakController { weak var value: BLEPreflightController? }
    var controller: BLEPreflightController? = BLEPreflightController(context:"released owner",adapter:fake)
    let weakController = WeakController(); weakController.value = controller
    controller!.run(peripheralID:UUID(),firmware:"G1L1FA2105AR")
    controller = nil
    check(weakController.value == nil && !fake.active && fake.stops.count == 1,"Releasing an owner closes the operation without a retain cycle")
}

print("BLE preflight offline: \(checks) checks passed; 12 packet/ACK/callback combinations, typed readiness/connection/setup/exchange messages, \(normalPacketCount) packet boundaries × 3 lifecycle interruptions, UI explicit actions/cancellation/generation/privacy, deadlines, late callbacks and disabled native submission")
print("No Bluetooth manager, physical printer, image upload, settings/clock write or print was used.")
