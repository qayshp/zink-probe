import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

private var checks = 0
func check(_ value: Bool, _ message: String = "check failed", file: StaticString = #file, line: UInt = #line) {
    checks += 1
    precondition(value, message, file: file, line: line)
}
func refuses(_ body: () throws -> Void) {
    do { try body(); fatalError("Expected refusal") } catch { checks += 1 }
}
func makeJPEG() -> Data {
    let context = CGContext(data:nil,width:768,height:1152,bitsPerComponent:8,bytesPerRow:0,
        space:CGColorSpace(name:CGColorSpace.sRGB)!,bitmapInfo:CGImageAlphaInfo.noneSkipLast.rawValue)!
    context.setFillColor(CGColor(gray:0.5,alpha:1)); context.fill(CGRect(x:0,y:0,width:768,height:1152))
    context.setFillColor(CGColor(red:0.1,green:0.4,blue:0.8,alpha:1)); context.fill(CGRect(x:120,y:220,width:400,height:600))
    let data = NSMutableData(), destination = CGImageDestinationCreateWithData(data,UTType.jpeg.identifier as CFString,1,nil)!
    CGImageDestinationAddImage(destination,context.makeImage()!,[kCGImageDestinationLossyCompressionQuality:1] as CFDictionary)
    precondition(CGImageDestinationFinalize(destination)); return data as Data
}
final class VirtualClock { var now = 0.0 }

/// A deterministic ATT peer, not firmware emulation. It only sees BLE sequence
/// packets. The existing memory printer supplies protocol responses after a
/// complete message has been assembled; no HP+ framing crosses this boundary.
final class PacketPeer: BLEPacketIO {
    let printer: SimulatedPrinter
    var mtu: Int, ackPeriod: Int, platformLimit: Int
    var notificationsFirst = false, inlineCallbacks = false
    var noReady = false, omitWriteCallback = false, dropConfigure = false
    var stopBeforePacket: Int?, endAfterPacket: Int?, failedAfterPacket: Int?, omitCallbackAt: Int?
    var malformedOpcode: UInt8?, duplicateOpcode: UInt8?
    var packetWrites: [[UInt8]] = [], packetOpcodes: [UInt8] = []
    var closeCount = 0, openCount = 0, clientACKs = 0
    private(set) var closed = false
    private var callback: ((BLEPacketIOEvent)->Void)?
    private var lateCallback: ((BLEPacketIOEvent)->Void)?
    private var events: [BLEPacketIOEvent] = []
    private var request: [UInt8] = [], expectedSequence = 1
    private var pendingNotifications: [[UInt8]] = []
    private var outstandingNativeWrites = 0
    private var currentOpcode: UInt8 = 0
    init(printer: SimulatedPrinter = SimulatedPrinter(), mtu: Int = 514, ackPeriod: Int = 0, platformLimit: Int = 512) {
        self.printer = printer; self.mtu = mtu; self.ackPeriod = ackPeriod; self.platformLimit = platformLimit
    }
    func open(_ handler: @escaping (BLEPacketIOEvent)->Void) {
        openCount += 1; callback = handler; lateCallback = handler
        if !noReady { events.append(.ready(writeLimit:platformLimit)) }
    }
    func write(_ packet: [UInt8]) -> Bool {
        guard !closed else { return false }
        if packetWrites.count == stopBeforePacket { return false }
        check(outstandingNativeWrites == 0, "More than one native BLE write outstanding")
        check(!packet.isEmpty && packet.count <= platformLimit, "Platform packet bound")
        outstandingNativeWrites = 1
        packetWrites.append(packet)
        if packet == [0] {
            clientACKs += 1; packetOpcodes.append(0)
            scheduleCallbackAndNotifications()
        } else {
            check(packet.count >= 2, "Missing sequence or payload")
            let sequence = Int(packet[0] & 127), final = packet[0] & 128 != 0
            check(sequence == expectedSequence, "Outgoing BLE sequence")
            if sequence == 1 {
                check(packet.dropFirst().prefix(3) != [72,80,43], "HP+ header must never cross GATT")
                currentOpcode = packet[1]
            }
            packetOpcodes.append(currentOpcode)
            request += packet.dropFirst(); expectedSequence += 1
            if final {
                let payload = request; request = []; expectedSequence = 1
                let reply: [UInt8]?
                if payload == [10,1,0] {
                    reply = dropConfigure ? nil : [11,1,UInt8(mtu & 255),UInt8(mtu >> 8),UInt8(ackPeriod)]
                } else {
                    printer.requests.append(payload)
                    var response = printer.respond(payload)
                    // A valid unknown capability TLV expands the reply enough
                    // to exercise ACK periods 2 and 7 at the 20-byte MTU.
                    if payload.first == 40 { response += [99,200,0] + [UInt8](repeating:0,count:200) }
                    reply = printer.droppedOpcode == payload.first || (printer.dropFinalAck && payload.first == 14 && printer.uploaded) ? nil : response
                }
                if let reply {
                    pendingNotifications = try! BLEPacketCodec.fragments(reply,packetLimit:mtu)
                    if payload.first == malformedOpcode { pendingNotifications[0][0] = 0x82 }
                    if payload.first == duplicateOpcode { pendingNotifications.insert(pendingNotifications[0],at:1) }
                }
                scheduleCallbackAndNotifications()
            } else if !omitWriteCallback { events.append(.written) }
        }
        let index = packetWrites.count-1
        if index == omitCallbackAt {
            events.removeAll { event in if case .written = event { return true }; return false }
        }
        if index == endAfterPacket { events = [.ended]; pendingNotifications = [] }
        if index == failedAfterPacket { events = [.failed]; pendingNotifications = [] }
        if inlineCallbacks { while !events.isEmpty && !closed { step() } }
        return true
    }
    private func releaseNotifications() {
        while !pendingNotifications.isEmpty {
            let packet = pendingNotifications.removeFirst(); events.append(.notification(packet))
            let sequence = Int(packet[0] & 127), final = packet[0] & 128 != 0
            if !final && ackPeriod > 0 && sequence % ackPeriod == 0 { break }
        }
    }
    private func scheduleCallbackAndNotifications() {
        if notificationsFirst { releaseNotifications(); if !omitWriteCallback { events.append(.written) } }
        else { if !omitWriteCallback { events.append(.written) }; releaseNotifications() }
    }
    func step() {
        guard !closed, !events.isEmpty else { return }
        let event = events.removeFirst()
        if case .written = event { check(outstandingNativeWrites == 1); outstandingNativeWrites = 0 }
        callback?(event)
    }
    func inject(_ event: BLEPacketIOEvent) { callback?(event) }
    func late(_ event: BLEPacketIOEvent) { lateCallback?(event) }
    func close() { closeCount += 1; closed = true; callback = nil; events = []; pendingNotifications = [] }
}

let image = try PreparedJobImage(jpeg:makeJPEG())
let settings = JobBinding.Settings(layout:"Preserve edges",quality:100)
let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
try FileManager.default.createDirectory(at:directory,withIntermediateDirectories:true)
defer { try? FileManager.default.removeItem(at:directory) }
func store(_ name: String) throws -> JobJournal { try JobJournal(url:directory.appendingPathComponent(name+".sqlite")) }
func bind(_ store: JobJournal, id: UUID = UUID(), prepared: PreparedJobImage = image) throws -> JobBinding {
    let peer = SimulatedPrinter(); var preflight = try ReadOnlyPreflight()
    while !preflight.complete { try preflight.accept(peer.respond(preflight.next())) }
    return try store.bind(id:id,image:prepared,settings:settings,
        printer:VerifiedPrinter(preflight:preflight,expectedFirmware:peer.firmware,now:0,date:Date(timeIntervalSince1970:0)),now:0)
}
final class Attempt {
    let clock: VirtualClock, io: PacketPeer, bridge: BLESubmissionDuplex, pump: AccessoryStreamPump, driver: AccessoryStreamDriver
    private let session: BLECoordinatorSession?
    init(pump: AccessoryStreamPump, clock: VirtualClock, io: PacketPeer, readOnly: Bool = false) {
        self.clock = clock; self.io = io; self.pump = pump
        session = nil
        bridge = BLESubmissionDuplex(io:io,clock:{ clock.now },policy:readOnly ? .readOnly : .singleJobSubmission)
        driver = AccessoryStreamDriver(pump:pump,io:bridge,clock:{ clock.now },update:{ _ in })
    }
    init(session: BLECoordinatorSession, clock: VirtualClock, io: PacketPeer) {
        self.session = session; self.clock = clock; self.io = io
        pump = session.pump; bridge = session.duplex; driver = session.driver
    }
    func step() {
        clock.now += 0.001; io.step()
        if let session { session.tick() } else { bridge.tick(); driver.tick() }
    }
    func run() {
        driver.start()
        for _ in 0..<400000 { if driver.closed { return }; step() }
        fatalError("BLE attempt did not terminate")
    }
}
func submission(_ journal: JobJournal, _ binding: JobBinding, io: PacketPeer = PacketPeer(), readOnly: Bool = false) throws -> Attempt {
    let clock = VirtualClock()
    if !readOnly {
        let session = try BLECoordinatorSession.authorizedSubmission(io:io,reviewed:binding,journal:journal,clock:{ clock.now },pollInterval:0.01,update:{ _ in })
        return Attempt(session:session,clock:clock,io:io)
    }
    let permit = try journal.authorizePrintOnce(binding)
    let coordinator = try SubmissionCoordinator(boundJob:binding.id,journal:journal,now:0,pollInterval:0.01,authorization:permit)
    let pump = try AccessoryStreamPump(coordinator:coordinator,permit:permit,journal:journal,now:0)
    return Attempt(pump:pump,clock:clock,io:io,readOnly:readOnly)
}

func assertNoReplay(_ journal: JobJournal, _ binding: JobBinding) throws {
    refuses { _ = try journal.authorizePrintOnce(binding) }
    refuses { _ = try SubmissionCoordinator(boundJob:binding.id,journal:journal,now:0) }
}

let processID = UUID(uuidString:"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")!
if CommandLine.arguments.count == 3 {
    let mode = CommandLine.arguments[1], journal = try JobJournal(url:URL(fileURLWithPath:CommandLine.arguments[2]))
    if mode == "race-permit" {
        do { _ = try journal.authorizePrintOnce(journal.binding(processID)!); _exit(0) }
        catch { _exit(2) }
    }
    let binding = try bind(journal,id:processID), attempt = try submission(journal,binding,io:PacketPeer(mtu:20,ackPeriod:1,platformLimit:20))
    attempt.driver.start()
    for _ in 0..<400000 {
        attempt.step()
        let record = try journal.record(binding.id)
        let reached = (mode == "pending-start" && record?.pendingOpcode == 12)
            || (mode == "partial-BLE-chunk" && attempt.io.packetOpcodes.last == 14 && attempt.io.packetWrites.last!.first! & 128 == 0)
            || (mode == "uploaded" && record?.uploadAcknowledged == true)
        if reached {
            try? FileManager.default.removeItem(at:directory)
            _exit(0) // Intentionally skip transport, driver and SQLite destructors.
        }
        if attempt.driver.closed { break }
    }
    fatalError("Requested BLE process-death boundary was not reached")
}

// Peer message maximum and the BLE sequence space are independent bounds. At
// ATT20, 127 × 19 payload bytes is safe even if setup advertises 4096 bytes.
do {
    let journal = try store("maximum-4096"), binding = try bind(journal)
    let peer = PacketPeer(mtu:20,ackPeriod:7,platformLimit:20); peer.printer.maximum = 4096
    let attempt = try submission(journal,binding,io:peer); attempt.run()
    check(attempt.pump.succeeded && Data(peer.printer.uploadedData) == image.jpeg && peer.printer.startCount == 1)
    check(attempt.bridge.maximumMessagePayload == 2413)
    let writes = peer.printer.requests.filter { $0.first == 14 }
    check(writes.allSatisfy { $0.count <= 2413 } && writes.contains { $0.count == 2413 })
}

// Full saved-byte transfers at bootstrap/negotiated ATT limits. The 514-byte
// protocol MTU is intentionally distinct from iOS's 512-byte native limit.
var baselineMutationPackets: [Int] = []
var firstSmallMTUChunkPackets: [Int] = []
var firstACKIndex: Int?
for mtu in [20,514] {
    for period in [0,1,2,7] {
        for responseFirst in [false,true] {
            let journal = try store("success-\(mtu)-\(period)-\(responseFirst)"), binding = try bind(journal)
            let peer = PacketPeer(mtu:mtu,ackPeriod:period,platformLimit:mtu == 20 ? 20 : 512)
            peer.notificationsFirst = responseFirst
            peer.printer.requireEmptyFinal = responseFirst
            let attempt = try submission(journal,binding,io:peer); attempt.run()
            check(attempt.pump.succeeded,"Full BLE job \(mtu)/\(period)/\(responseFirst): \(attempt.pump.result); bridge \(attempt.bridge.failureReason ?? "none")")
            check(Data(peer.printer.uploadedData) == image.jpeg && peer.printer.startCount == 1)
            check(try journal.attemptState(binding.id) == "completed")
            check(peer.closeCount == 1 && peer.openCount == 1)
            check(attempt.bridge.txQueuedBytes == attempt.bridge.txAcknowledgedBytes)
            check(attempt.bridge.writeCallbacks == peer.packetWrites.count)
            check(attempt.bridge.protocolMTU == mtu && attempt.bridge.acknowledgementPeriod == period)
            check(period == 0 || mtu != 20 || peer.clientACKs > 0)
            try assertNoReplay(journal,binding)
            let before = peer.packetWrites.count; attempt.driver.start(); attempt.driver.tick(); attempt.bridge.tick()
            peer.late(.written); peer.late(.notification([0x81,1])); peer.late(.ended)
            check(peer.packetWrites.count == before && peer.closeCount == 1)
            if mtu == 514 && period == 0 && !responseFirst {
                baselineMutationPackets = peer.packetOpcodes.enumerated().compactMap { [UInt8(12),14,48].contains($0.element) ? $0.offset : nil }
            }
            if mtu == 20 && period == 0 && !responseFirst, let first = peer.packetOpcodes.firstIndex(of:14) {
                for index in first..<peer.packetOpcodes.count {
                    firstSmallMTUChunkPackets.append(index)
                    if peer.packetWrites[index][0] & 128 != 0 { break }
                }
            }
            if mtu == 20 && period == 1 && !responseFirst { firstACKIndex = peer.packetOpcodes.firstIndex(of:0) }
        }
    }
}

// Downstream transport ACKs use the same one-write-at-a-time callback contract.
// Losing or failing an ACK's own native callback cannot make the receiver
// advance, authorize a print or silently send the ACK again.
check(firstACKIndex != nil)
for fault in ["missing-ACK-callback","failed-ACK-write"] {
    let clock = VirtualClock(), peer = PacketPeer(mtu:20,ackPeriod:1,platformLimit:20)
    if fault == "missing-ACK-callback" { peer.omitCallbackAt = firstACKIndex }
    else { peer.failedAfterPacket = firstACKIndex }
    let session = try BLECoordinatorSession.preflight(io:peer,expectedDeviceID:peer.printer.device,
        expectedFirmware:peer.printer.firmware,clock:{ clock.now },update:{ _ in })
    let attempt = Attempt(session:session,clock:clock,io:peer); attempt.run()
    check(!attempt.pump.succeeded && peer.printer.mutationCount == 0 && peer.closeCount == 1)
    check(peer.clientACKs == 1)
}

// Inline native callbacks are queued until the virtual writer has returned its
// accepted count; notifications never advance an exchange before write success.
do {
    let journal = try store("inline"), binding = try bind(journal), peer = PacketPeer(mtu:20,ackPeriod:1,platformLimit:20)
    peer.notificationsFirst = true; peer.inlineCallbacks = true
    let attempt = try submission(journal,binding,io:peer); attempt.run()
    check(attempt.pump.succeeded && Data(peer.printer.uploadedData) == image.jpeg && peer.printer.startCount == 1)
}

// Valid JPEG comment segments enlarge the exact saved file without changing its
// raster. This is a transport byte-volume test, not image-quality evidence.
// Thousands of fully inline native callbacks must yield bounded work and finish.
let paddedImage: PreparedJobImage = try {
    var bytes = Array(image.jpeg.prefix(2))
    for _ in 0..<8 { bytes += [0xff,0xfe,0xff,0xff] + [UInt8](repeating:0,count:65533) }
    bytes += image.jpeg.dropFirst(2)
    return try PreparedJobImage(jpeg:Data(bytes))
}()
do {
    let journal = try store("large-inline"), binding = try bind(journal,prepared:paddedImage)
    let peer = PacketPeer(mtu:20,ackPeriod:1,platformLimit:20)
    peer.notificationsFirst = true; peer.inlineCallbacks = true
    let attempt = try submission(journal,binding,io:peer); attempt.run()
    check(attempt.pump.succeeded && Data(peer.printer.uploadedData) == paddedImage.jpeg && peer.printer.startCount == 1)
    check(peer.packetWrites.count > 10000 && peer.closeCount == 1)
}

// Every outgoing mutating packet boundary in a full 512-byte ATT transfer:
// refusal before a write, disconnect after acceptance, and host cancellation.
// SQLite claim/pending intent must survive even if no complete PrintStart
// message reached the peer. None can authorize a second attempt.
check(!baselineMutationPackets.isEmpty)
for index in baselineMutationPackets {
    for fault in ["refusal","disconnect","cancel","callback","native-error"] {
        let journal = try store("cut-\(index)-\(fault)"), binding = try bind(journal), peer = PacketPeer()
        if fault == "refusal" { peer.stopBeforePacket = index }
        if fault == "disconnect" { peer.endAfterPacket = index }
        if fault == "callback" { peer.omitCallbackAt = index }
        if fault == "native-error" { peer.failedAfterPacket = index }
        let attempt = try submission(journal,binding,io:peer)
        if fault == "cancel" {
            attempt.driver.start()
            while !attempt.driver.closed && peer.packetWrites.count <= index { attempt.step() }
            attempt.driver.cancel("Simulated Share host dismissal after native packet acceptance")
        }
        attempt.run()
        check(!attempt.pump.succeeded && peer.printer.startCount <= 1 && peer.closeCount == 1)
        check(try journal.attemptState(binding.id) == "uncertain")
        check(try journal.record(binding.id) != nil)
        try assertNoReplay(journal,binding); refuses { try journal.discardDraft(binding.id) }
    }
}

// Every fragment of a 1000-byte upload message at MTU20 is also interrupted,
// rather than relying only on the two-fragment native-limit configuration.
for index in firstSmallMTUChunkPackets {
    let journal = try store("small-fragment-\(index)"), binding = try bind(journal)
    let peer = PacketPeer(mtu:20,ackPeriod:0,platformLimit:20); peer.endAfterPacket = index
    let attempt = try submission(journal,binding,io:peer); attempt.run()
    check(!attempt.pump.succeeded && peer.printer.startCount == 1 && peer.closeCount == 1)
    check(try journal.attemptState(binding.id) == "uncertain")
    try assertNoReplay(journal,binding)
}

// Lost application responses, including an upload accepted by the peer whose
// final reply is lost, stay uncertain and block a fresh device claim.
for fault in ["start","properties","chunk","final","wrong-offset","foreign-job","extra-page","calibration"] {
    let journal = try store("lost-\(fault)"), binding = try bind(journal), peer = PacketPeer(mtu:20,ackPeriod:2,platformLimit:20)
    if fault == "start" { peer.printer.droppedOpcode = 12 }
    if fault == "properties" { peer.printer.droppedOpcode = 48 }
    if fault == "chunk" { peer.printer.droppedOpcode = 14 }
    peer.printer.dropFinalAck = fault == "final"; peer.printer.badFinalOffset = fault == "wrong-offset"
    peer.printer.foreignJob = fault == "foreign-job"; peer.printer.extraPage = fault == "extra-page"
    peer.printer.changedCalibration = fault == "calibration"
    let attempt = try submission(journal,binding,io:peer); attempt.run()
    check(!attempt.pump.succeeded && peer.printer.startCount == 1 && peer.closeCount == 1)
    check(try journal.attemptState(binding.id) == "uncertain")
    try assertNoReplay(journal,binding)
    refuses { _ = try bind(journal) }
    if fault == "final" {
        let reopened = try JobJournal(url:directory.appendingPathComponent("lost-final.sqlite"))
        let clock = VirtualClock(); clock.now = attempt.clock.now
        peer.printer.dropFinalAck = false
        let recoveryIO = PacketPeer(printer:peer.printer,mtu:20,ackPeriod:1,platformLimit:20)
        let recovery = try BLECoordinatorSession.recovery(io:recoveryIO,id:binding.id,journal:reopened,clock:{ clock.now },update:{ _ in })
        let reader = Attempt(session:recovery,clock:clock,io:recoveryIO)
        let before = peer.printer.mutationCount; reader.run()
        check(!reader.pump.succeeded && peer.printer.mutationCount == before && peer.printer.startCount == 1)
        try assertNoReplay(reopened,binding)
    }
}

// Read-only native policy remains a separate barrier even when an authorized
// coordinator is accidentally supplied to the simulated transport composition.
do {
    let journal = try store("native-policy"), binding = try bind(journal), peer = PacketPeer()
    let attempt = try submission(journal,binding,io:peer,readOnly:true); attempt.run()
    check(!attempt.pump.succeeded && peer.printer.mutationCount == 0)
    check(try journal.record(binding.id)?.pendingOpcode == 12)
    try assertNoReplay(journal,binding)
}

// Invalid session setup, malformed/replayed notifications, missing callbacks,
// and discovery/response deadlines terminate before any possible print write.
for fault in ["no-ready","configure-timeout","write-callback","sequence","duplicate","wrong-printer","paused","clock-flag","reversed-clock","native-error","invalid-mtu","invalid-ACK","invalid-platform"] {
    let clock = VirtualClock(), peer = PacketPeer(mtu:20,ackPeriod:1,platformLimit:20)
    peer.noReady = fault == "no-ready"; peer.dropConfigure = fault == "configure-timeout"
    peer.omitWriteCallback = fault == "write-callback"
    if fault == "sequence" { peer.malformedOpcode = 4 }
    if fault == "duplicate" { peer.duplicateOpcode = 4 }
    peer.printer.mismatchIdentity = fault == "wrong-printer"; peer.printer.paused = fault == "paused"
    peer.printer.initialFlags = fault == "clock-flag" ? 1 : 0
    if fault == "invalid-mtu" { peer.mtu = 19 }
    if fault == "invalid-ACK" { peer.ackPeriod = 128 }
    if fault == "invalid-platform" { peer.platformLimit = 19 }
    if fault == "native-error" { peer.failedAfterPacket = 0 }
    let pump = try AccessoryStreamPump(expectedDeviceID:peer.printer.device,expectedFirmware:peer.printer.firmware,now:0)
    let attempt = Attempt(pump:pump,clock:clock,io:peer,readOnly:true)
    if fault == "reversed-clock" { attempt.driver.start(); attempt.step(); clock.now = -1 }
    attempt.run()
    check(!pump.succeeded && peer.closeCount == 1 && peer.printer.mutationCount == 0,"Fault \(fault) must fail closed")
    let before = peer.packetWrites.count; peer.late(.written); peer.late(.notification([0x81,5,1,0])); attempt.bridge.tick(); attempt.driver.tick()
    check(peer.packetWrites.count == before && peer.closeCount == 1)
}

// The generic coordinator resolves its transport limit before claiming. Invalid
// injected values fail without allocating a job, rather than failing on a later
// oversized upload after PrintStart may already have reached the peer.
for maximum in [0,15,4097] {
    let journal = try store("invalid-transport-\(maximum)"), binding = try bind(journal), peer = PacketPeer(), clock = VirtualClock()
    let permit = try journal.authorizePrintOnce(binding)
    let coordinator = try SubmissionCoordinator(boundJob:binding.id,journal:journal,now:0,authorization:permit,transportMaximum:{ maximum })
    let pump = try AccessoryStreamPump(coordinator:coordinator,permit:permit,journal:journal,now:0)
    let attempt = Attempt(pump:pump,clock:clock,io:peer); attempt.run()
    check(!pump.succeeded && peer.printer.mutationCount == 0)
    check(try journal.record(binding.id) == nil && journal.attemptState(binding.id) == "notSubmitted")
    try assertNoReplay(journal,binding)
}

// The journal's single-use authorization is transport-independent: a completed
// or uncertain BLE attempt cannot be replayed through the accessory transport.
// Two independent journal objects arbitrate confirmations through SQLite.
do {
    let url = directory.appendingPathComponent("competing.sqlite"), a = try JobJournal(url:url), binding = try bind(a)
    let b = try JobJournal(url:url), token = try a.authorizePrintOnce(binding)
    refuses { _ = try b.authorizePrintOnce(binding) }
    let coordinator = try SubmissionCoordinator(boundJob:binding.id,journal:a,now:0,authorization:token)
    _ = try AccessoryStreamPump(coordinator:coordinator,permit:token,journal:a,now:0)
    refuses { _ = try AccessoryStreamPump(coordinator:coordinator,permit:token,journal:b,now:0) }
    refuses { _ = try SubmissionCoordinator(boundJob:binding.id,journal:b,now:0) }
}

// The production facade rejects submission before authorization, central-manager
// creation or a connection. No phone or adapter is needed for this test.
do {
    let journal = try store("production-disabled"), binding = try bind(journal)
    let adapter = NativeBLEAdapter()
    refuses { try adapter.submitOnce(peripheralID:UUID(),reviewed:binding,journal:journal,update:{ _ in }) }
    check(try journal.attemptState(binding.id) == nil)
    check(try journal.record(binding.id) == nil)
    check(try journal.binding(binding.id) == binding)
}

// A new process reopens only the journal after each abrupt exit. In the partial
// packet case the host has a durable intent but the peer never assembled that
// message. Recovery observes; it never reloads/replays the prepared JPEG.
for boundary in ["pending-start","partial-BLE-chunk","uploaded"] {
    let url = directory.appendingPathComponent("crash-\(boundary).sqlite")
    let child = Process(); child.executableURL = URL(fileURLWithPath:CommandLine.arguments[0]); child.arguments = [boundary,url.path]
    try child.run(); child.waitUntilExit(); check(child.terminationStatus == 0)
    let journal = try JobJournal(url:url), binding = try journal.binding(processID)!
    try assertNoReplay(journal,binding); refuses { try journal.discardDraft(binding.id) }
    if boundary == "pending-start" {
        refuses { _ = try SubmissionCoordinator(recover:binding.id,journal:journal,now:0) }
    } else {
        let peer = PacketPeer(mtu:20,ackPeriod:1,platformLimit:20), clock = VirtualClock()
        let record = try journal.record(binding.id)!
        peer.printer.job = Int(record.printerJobID!); peer.printer.uploaded = boundary == "uploaded"
        let recovery = try BLECoordinatorSession.recovery(io:peer,id:binding.id,journal:journal,clock:{ clock.now },update:{ _ in })
        let attempt = Attempt(session:recovery,clock:clock,io:peer); attempt.run()
        check(peer.printer.mutationCount == 0 && peer.printer.uploadedData.isEmpty && peer.closeCount == 1)
        check(attempt.pump.succeeded == (boundary == "uploaded"))
        try assertNoReplay(journal,binding)
    }
}

// The shared native composition leaves room for bounded CoreBluetooth discovery
// and subscription. The old stream default's ten seconds must not expire a
// legitimate fifteen-second native setup; ninety seconds is still terminal.
for delay in [15.0,90.0] {
    let clock = VirtualClock(), peer = PacketPeer(); peer.noReady = true
    let session = try BLECoordinatorSession.preflight(io:peer,expectedDeviceID:peer.printer.device,
        expectedFirmware:peer.printer.firmware,clock:{ clock.now },update:{ _ in })
    let attempt = Attempt(session:session,clock:clock,io:peer)
    session.start(); clock.now = delay; session.tick()
    peer.inject(.ready(writeLimit:512)); attempt.run()
    check(attempt.pump.succeeded == (delay < 90) && peer.printer.mutationCount == 0 && peer.closeCount == 1)
}

// Failure while constructing the shared session cannot leave an authorization
// that can later be replayed or issue any native writes.
do {
    let journal = try store("factory-clock-failure"), binding = try bind(journal), peer = PacketPeer()
    refuses { _ = try BLECoordinatorSession.authorizedSubmission(io:peer,reviewed:binding,journal:journal,clock:{ .nan },update:{ _ in }) }
    check(try journal.attemptState(binding.id) == "notSubmitted")
    check(peer.openCount == 0 && peer.packetWrites.isEmpty)
    try assertNoReplay(journal,binding)
}

do {
    let url = directory.appendingPathComponent("racing-processes.sqlite"), journal = try JobJournal(url:url)
    _ = try bind(journal,id:processID)
    func contender() throws -> Process {
        let process = Process(); process.executableURL = URL(fileURLWithPath:CommandLine.arguments[0]); process.arguments = ["race-permit",url.path]
        try process.run(); return process
    }
    let first = try contender(), second = try contender(); first.waitUntilExit(); second.waitUntilExit()
    check([first.terminationStatus,second.terminationStatus].sorted() == [0,2])
    check(try journal.attemptState(processID) == "reserved")
}

print("BLE submission offline: \(checks) checks passed; \(image.jpeg.count) / \(paddedImage.jpeg.count) exact JPEG bytes, 16 MTU/ACK/callback combinations, \(baselineMutationPackets.count) mutation-packet boundaries × 5 interruptions, \(firstSmallMTUChunkPackets.count) MTU20 upload fragments and 3 abrupt process exits")
print("No Bluetooth manager, device, print job or paper was used. Native BLE submission remains disabled; recovery never resubmits and durable permits cannot be replayed across transports.")
