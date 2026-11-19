import Foundation

/// Allows this session's fixed setup and reads plus one exact clock payload.
/// The authorization requires identity and status checks on the same
/// connection. It is spent before radio I/O.
final class BLEClockWriteAuthorization {
    private var clockPayload: [UInt8]?
    private(set) var spent = false

    fileprivate func authorize(_ payload: [UInt8]) throws {
        guard !spent, clockPayload == nil, payload.count == 9, payload.first == 24 else {
            throw ReadOnlyPreflight.Failure.invalid("Clock write authorization refused.")
        }
        clockPayload = payload
    }

    func allows(_ payload: [UInt8]) -> Bool {
        if [[4,1], [4,9], [4,6], [36,0,16], [26,4], [8,1,2,3,5,6,7], [44], [8,1]].contains(payload) { return true }
        guard !spent, payload == clockPayload else { return false }
        spent = true; clockPayload = nil
        return true
    }
}

/// A separate, single-action clock session. It shares the BLE packet bridge
/// and the date/offset serializer with the other adapters, but has no print
/// coordinator, image, journal, or print authorization API.
final class BLEClockSession {
    enum Outcome: Equatable {
        case verified, notNeeded
        case refused(reason: String), possiblyWritten(reason: String), acknowledgedUnverified(reason: String)

        var summary: String {
            switch self {
            case .verified: return "The printer acknowledged the clock update and cleared its invalid-clock flag."
            case .notNeeded: return "The printer no longer reports an invalid clock. No update was sent."
            case .refused(let reason): return "\(reason) No clock update was sent."
            case .possiblyWritten(let reason):
                return "\(reason) The update may have reached the printer. Run the read-only check before deciding whether to sync again."
            case .acknowledgedUnverified(let reason):
                return "\(reason) The printer acknowledged the update, but flag clearance could not be verified. Run the read-only check."
            }
        }
    }

    private enum Stage { case identity, setup, pause, status, jobs, clock }
    let duplex: BLESubmissionDuplex
    private let authorization = BLEClockWriteAuthorization()
    private let expectedFirmware: String
    private let clock: () -> TimeInterval
    private let wallClock: () -> Date
    private let timeZone: () -> TimeZone
    private let update: (Outcome) -> Void
    private var identity: ReadOnlyPreflight
    private var observation: ReadOnlyPreflight
    private var sync: ClockSync?
    private var stage: Stage = .identity
    private var exchange: AccessoryExchange?
    private var opened = Set<AccessoryStreamPump.Side>()
    private var deadline = 0.0
    private var started = false
    private var driving = false
    private(set) var closed = false

    init(io: BLEPacketIO, expectedDeviceID: String, expectedFirmware: String,
         clock: @escaping () -> TimeInterval, wallClock: @escaping () -> Date = { Date() },
         timeZone: @escaping () -> TimeZone = { .current }, update: @escaping (Outcome) -> Void) throws {
        guard !expectedFirmware.isEmpty, expectedFirmware.utf8.count <= 128,
              expectedFirmware.utf8.allSatisfy({ (32...126).contains($0) }) else {
            throw ReadOnlyPreflight.Failure.invalid("Invalid expected clock-session firmware.")
        }
        identity = try ReadOnlyPreflight(expectedDeviceID: expectedDeviceID)
        observation = try ReadOnlyPreflight.observation()
        self.expectedFirmware = expectedFirmware
        self.clock = clock; self.wallClock = wallClock; self.timeZone = timeZone; self.update = update
        duplex = BLESubmissionDuplex(io: io, clock: clock, policy: .clockSync(authorization), setupTimeout: 90)
    }

    func start() {
        guard !started, !closed else { return }
        started = true; deadline = clock() + 180
        guard deadline.isFinite else { cancel("Clock-sync time source invalid."); return }
        duplex.open { [weak self] in self?.drive($0) }
    }

    func tick() {
        guard started, !closed else { return }
        duplex.tick()
        drive(nil)
    }

    func cancel(_ reason: String) {
        guard !closed else { return }
        if sync?.acknowledged == true { finish(.acknowledgedUnverified(reason: reason)) }
        else if authorization.spent { finish(.possiblyWritten(reason: reason)) }
        else { finish(.refused(reason: reason)) }
    }

    private func finish(_ result: Outcome) {
        closed = true
        duplex.close()
        update(result)
    }

    private func drive(_ event: AccessoryIOEvent?) {
        guard started, !closed, !driving else { return }
        driving = true
        defer { driving = false }
        switch event {
        case .opened(let side): opened.insert(side)
        case .failed, .ended: cancel("The BLE clock session was interrupted."); return
        default: break
        }
        let now = clock()
        guard now.isFinite, now < deadline else { cancel("The BLE clock session timed out."); return }
        guard opened.count == 2 else { return }
        do {
            try exchange?.check(now: now)
            if duplex.hasBytes {
                guard case .bytes(let bytes) = duplex.read(maximum: 4104),
                      let reply = try exchange?.receive(bytes, now: now) else {
                    throw ReadOnlyPreflight.Failure.invalid("Unexpected clock-sync reply.")
                }
                exchange = nil
                try accept(reply)
            }
            guard !closed, duplex.hasSpace else { return }
            if exchange == nil { exchange = try AccessoryExchange(payload: next(), now: now) }
            try exchange?.write(now: now, duplex.write)
        } catch ReadOnlyPreflight.Failure.invalid(let reason) {
            cancel(reason.hasSuffix(".") ? reason : reason + ".")
        } catch {
            cancel("The BLE clock exchange failed or timed out.")
        }
    }

    private func next() throws -> [UInt8] {
        switch stage {
        case .identity, .setup: return try identity.next()
        case .pause: return [26,4]
        case .status, .jobs: return try observation.next()
        case .clock:
            guard var sync else { throw ReadOnlyPreflight.Failure.invalid("Clock action is not authorized.") }
            let payload = try sync.next(now: wallClock(), zone: timeZone())
            self.sync = sync
            if !sync.acknowledged { try authorization.authorize(payload) }
            return payload
        }
    }

    private func accept(_ reply: [UInt8]) throws {
        switch stage {
        case .identity:
            try identity.accept(reply)
            guard identity.firmware == expectedFirmware else {
                throw ReadOnlyPreflight.Failure.invalid("The printer firmware does not match the checked Select.")
            }
            if !identity.deviceID.isEmpty { stage = .setup }
        case .setup:
            // Match the ordinary BLE preflight's connection-local setup. Do
            // not include an unexpected raw response in the user-facing result.
            do { try identity.accept(reply) }
            catch { throw ReadOnlyPreflight.Failure.invalid("The printer's connection setup could not be verified.") }
            stage = .pause
        case .pause:
            guard reply == [27,4,0] else {
                throw ReadOnlyPreflight.Failure.invalid("The printer is paused or its pause state could not be verified.")
            }
            stage = .status
        case .status:
            try observation.accept(reply)
            if observation.flags == 0 { finish(.notNeeded); return }
            guard observation.flags == 1, observation.printerState == 1, observation.currentJob == 0,
                  observation.queueState == 1, observation.battery >= 30, [1,2].contains(observation.power) else {
                throw ReadOnlyPreflight.Failure.invalid("The printer has another status, queue or power condition that blocks clock sync.")
            }
            stage = .jobs
        case .jobs:
            try observation.accept(reply)
            guard observation.jobs.isEmpty else {
                throw ReadOnlyPreflight.Failure.invalid("The printer queue is not empty.")
            }
            sync = try ClockSync(verifiedFlags: UInt32(observation.flags))
            stage = .clock
        case .clock:
            guard var sync else { throw ReadOnlyPreflight.Failure.invalid("Clock action is not authorized.") }
            try sync.accept(reply)
            self.sync = sync
            if sync.complete { finish(.verified) }
        }
    }
}
