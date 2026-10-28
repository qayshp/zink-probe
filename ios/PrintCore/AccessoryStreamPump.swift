import Foundation

/// Diagnostic/recovery output policy, with no enable-printing switch. Validate a whole frame
/// before its first byte, then allow only exact continuations of that frame.
struct ReadOnlyFrameGate {
    enum Failure: Error { case forbidden, changedContinuation, invalidWrite }
    private var remaining: [UInt8] = []
    private(set) var acceptedBytes = 0
    static func allows(_ payload: [UInt8]) -> Bool {
        if [[4,1],[4,9],[4,6],[36,0,16],[42],[26,4],[8,1,2,3,5,6,7],[44]].contains(payload) { return true }
        if payload.count == 3 && payload[0] == 40 && payload[2] == 1 { return true }
        return payload.count == 4 && payload[0] == 58 && payload[1] == 1
    }
    mutating func write(_ bytes: [UInt8], writer: ([UInt8]) -> Int) throws -> Int {
        if remaining.isEmpty {
            guard bytes.count >= 5, bytes.prefix(3) == [72,80,43], [1,2].contains(bytes[3]) else { throw Failure.forbidden }
            let width = Int(bytes[3]), header = 4 + width
            guard bytes.count >= header else { throw Failure.forbidden }
            let length = Int(bytes[4]) + (width == 2 ? Int(bytes[5])*256 : 0)
            guard length > 0, length <= 4096, bytes.count == header+length,
                  Self.allows(Array(bytes.dropFirst(header))) else { throw Failure.forbidden }
            remaining = bytes
        }
        guard bytes == remaining else { throw Failure.changedContinuation }
        let count = writer(bytes)
        guard count >= 0, count <= bytes.count else { throw Failure.invalidWrite }
        acceptedBytes += count; remaining.removeFirst(count)
        return count
    }
}

/// Fresh successful full preflight evidence. Not a print permit. Uptime is not
/// persisted or reused after a restart; saved jobs always need fresh checks.
struct VerifiedPrinter: Sendable {
    let deviceID: String
    let firmware: String
    let checkedAt: Date
    let uptime: TimeInterval
    init(preflight: ReadOnlyPreflight, expectedFirmware: String, now: TimeInterval, date: Date = Date()) throws {
        guard preflight.complete, !preflight.failed, preflight.readinessEvaluated,
              preflight.firmware == expectedFirmware, !expectedFirmware.isEmpty,
              now.isFinite, date.timeIntervalSince1970.isFinite else { throw JobJournal.Failure.invalidRecord }
        deviceID = preflight.deviceID; firmware = preflight.firmware; checkedAt = date; uptime = now
    }
}

/// Serial event pump shared by native streams and offline fault tests. The
/// coordinator initializer also permits tests of attempted upload behind the
/// default read-only output gate. The separate print initializer consumes a
/// durable one-job permit; there is no global print-enable flag.
final class AccessoryStreamPump {
    enum Side: Hashable { case input, output }
    private var reader: ReadOnlyPreflight?
    private var exchange: AccessoryExchange?
    private let coordinator: SubmissionCoordinator?
    private let expectedFirmware: String
    private let deadline: TimeInterval
    private let openDeadline: TimeInterval
    private var lastTime: TimeInterval
    private var opened = Set<Side>()
    private var gate = ReadOnlyFrameGate()
    private var printGate: SingleJobFrameGate?
    private(set) var terminal = false
    private(set) var succeeded = false
    private(set) var result = "Waiting for both accessory streams. Real printing is disabled."
    private(set) var receivedBytes = 0
    private(set) var verified: VerifiedPrinter?
    var acceptedBytes: Int { printGate?.acceptedBytes ?? gate.acceptedBytes }
    var acknowledgedImageBytes: Int { printGate?.acknowledgedBytes ?? 0 }
    var totalImageBytes: Int { printGate?.totalBytes ?? 0 }
    var jobState: String? { coordinator?.state.rawValue }
    var streamsOpened: Int { opened.count }
    init(expectedDeviceID: String? = nil, expectedFirmware: String, now: TimeInterval) throws {
        guard now.isFinite, !expectedFirmware.isEmpty else { throw JobJournal.Failure.invalidRecord }
        reader = try ReadOnlyPreflight(expectedDeviceID:expectedDeviceID)
        coordinator = nil; self.expectedFirmware = expectedFirmware
        lastTime = now; deadline = now+60; openDeadline = now+10
    }
    init(coordinator: SubmissionCoordinator, now: TimeInterval) {
        self.coordinator = coordinator; expectedFirmware = ""
        lastTime = now; deadline = now+180; openDeadline = now+10
    }
    init(coordinator: SubmissionCoordinator, permit: PrintPermit, journal: JobJournal, now: TimeInterval) throws {
        guard coordinator.localID == permit.binding.id else { throw JobJournal.Failure.blocked }
        printGate = try SingleJobFrameGate(permit:permit,journal:journal)
        self.coordinator = coordinator; expectedFirmware = ""
        lastTime = now; deadline = now+300; openDeadline = now+10
        result = "One-photo attempt authorized. Opening accessory streams."
    }
    func opened(_ side: Side, now: TimeInterval) { tick(now:now); if !terminal { opened.insert(side) } }
    func tick(now: TimeInterval) {
        guard !terminal else { return }
        guard now.isFinite, now >= lastTime, now < deadline,
              opened.count == 2 || now < openDeadline else { stop("Stream/open/overall deadline or monotonic clock violation"); return }
        lastTime = now
        do { try exchange?.check(now:now) } catch { stop("Read-only exchange timed out; no retry"); return }
        coordinator?.tick(now:now); finishCoordinator()
    }
    func writable(now: TimeInterval, writer: ([UInt8]) -> Int) {
        tick(now:now); guard !terminal, opened.count == 2 else { return }
        var policyFailure = false
        func output(_ bytes: [UInt8]) -> Int {
            do {
                if printGate != nil { return try printGate!.write(bytes,writer:writer) }
                return try gate.write(bytes,writer:writer)
            }
            catch { policyFailure = true; return -1 }
        }
        do {
            if let coordinator { coordinator.write(now:now,output) }
            else {
                if exchange == nil { exchange = try AccessoryExchange(payload:reader!.next(),now:now) }
                try exchange?.write(now:now,output)
            }
            if policyFailure { stop("Live output policy blocked a forbidden frame or invalid continuation; no retry"); return }
            finishCoordinator()
        } catch { stop("Stream write failed; no retry") }
    }
    func receive(_ bytes: [UInt8], now: TimeInterval) {
        tick(now:now); guard !terminal else { return }
        guard opened.count == 2, !bytes.isEmpty, receivedBytes + bytes.count <= (printGate == nil ? 262144 : 32*1024*1024) else { stop("Premature input or receive bound reached"); return }
        receivedBytes += bytes.count
        if let coordinator { coordinator.receive(bytes,now:now); finishCoordinator(); return }
        do {
            guard exchange != nil else { throw JobJournal.Failure.invalidRecord }
            if let reply = try exchange?.receive(bytes,now:now) {
                exchange = nil; try reader!.accept(reply)
                guard reader!.firmware == expectedFirmware else { throw ReadOnlyPreflight.Failure.invalid("Firmware differs from accessory metadata") }
                if reader!.complete {
                    verified = try VerifiedPrinter(preflight:reader!,expectedFirmware:expectedFirmware,now:now)
                    result = reader!.summary; succeeded = true; terminal = true
                }
            }
        } catch { stop("Read-only preflight stopped: \(error); no retry") }
    }
    func stop(_ reason: String) {
        guard !terminal else { return }
        exchange?.stop(); reader?.stop(); coordinator?.disconnected()
        verified = nil; terminal = true; result = reason
        finishAttempt()
    }
    private func finishCoordinator() {
        guard let coordinator, coordinator.terminal, !terminal else { return }
        terminal = true; succeeded = coordinator.state == .completed
        result = printGate == nil
            ? "Read-only recovery: \(coordinator.state.rawValue). \(coordinator.error ?? "No image resent.")"
            : "Print attempt: \(coordinator.state.rawValue). \(coordinator.error ?? "Protocol completion observed; check the physical photo.") No automatic resubmission."
        finishAttempt()
    }
    private func finishAttempt() {
        do { try printGate?.finish() }
        catch { succeeded = false; result += " Outcome storage failed; do not resubmit." }
    }
}
