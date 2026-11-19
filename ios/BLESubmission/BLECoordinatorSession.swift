import Foundation

/// Shared composition for the native facade and in-memory BLE peer tests. The
/// packet IO is injected, but authorization, immutable binding, durable journal,
/// output gate, coordinator and bridge are the same path in both compositions.
/// This type never creates CoreBluetooth objects or chooses a physical printer.
final class BLECoordinatorSession {
    let pump: AccessoryStreamPump
    let duplex: BLESubmissionDuplex
    let driver: AccessoryStreamDriver
    var closed: Bool { driver.closed }

    private init(pump: AccessoryStreamPump, duplex: BLESubmissionDuplex,
                 clock: @escaping () -> TimeInterval,
                 update: @escaping (AccessoryStreamPump) -> Void) {
        self.pump = pump
        self.duplex = duplex
        driver = AccessoryStreamDriver(pump:pump,io:duplex,clock:clock,update:update)
    }

    static func preflight(io: BLEPacketIO, expectedDeviceID: String? = nil,
                          expectedFirmware: String, clock: @escaping () -> TimeInterval,
                          update: @escaping (AccessoryStreamPump) -> Void) throws -> BLECoordinatorSession {
        let pump = try AccessoryStreamPump(expectedDeviceID:expectedDeviceID,
            expectedFirmware:expectedFirmware,now:clock(),openingTimeout:90)
        let duplex = BLESubmissionDuplex(io:io,clock:clock,policy:.readOnly,setupTimeout:90)
        return BLECoordinatorSession(pump:pump,duplex:duplex,clock:clock,update:update)
    }

    static func recovery(io: BLEPacketIO, id: UUID, journal: JobJournal,
                         clock: @escaping () -> TimeInterval,
                         update: @escaping (AccessoryStreamPump) -> Void) throws -> BLECoordinatorSession {
        let now = clock(), coordinator = try SubmissionCoordinator(recover:id,journal:journal,now:now)
        let pump = AccessoryStreamPump(coordinator:coordinator,now:now,openingTimeout:90)
        let duplex = BLESubmissionDuplex(io:io,clock:clock,policy:.readOnly,setupTimeout:90)
        return BLECoordinatorSession(pump:pump,duplex:duplex,clock:clock,update:update)
    }

    /// Native callers must first pass the BLESubmissionAvailability build gate.
    /// Tests call this exact factory with an in-memory peer.
    /// Creating a session reserves and consumes one permit, but sends no bytes
    /// until start(). A failed construction finalizes that spent attempt.
    static func authorizedSubmission(io: BLEPacketIO, reviewed: JobBinding,
                                     journal: JobJournal, clock: @escaping () -> TimeInterval,
                                     pollInterval: TimeInterval = 2,
                                     update: @escaping (AccessoryStreamPump) -> Void) throws -> BLECoordinatorSession {
        let permit = try journal.authorizePrintOnce(reviewed)
        do {
            let now = clock()
            let duplex = BLESubmissionDuplex(io:io,clock:clock,policy:.singleJobSubmission,setupTimeout:90)
            let coordinator = try SubmissionCoordinator(boundJob:reviewed.id,journal:journal,
                now:now,pollInterval:pollInterval,authorization:permit,
                transportMaximum:{ duplex.maximumMessagePayload })
            let pump = try AccessoryStreamPump(coordinator:coordinator,permit:permit,journal:journal,
                now:now,openingTimeout:90)
            return BLECoordinatorSession(pump:pump,duplex:duplex,clock:clock,update:update)
        } catch {
            try? journal.finishPrintAttempt(reviewed.id)
            throw error
        }
    }

    func start() { driver.start() }
    func tick() { duplex.tick(); driver.tick() }
    func cancel(_ reason: String) { driver.cancel(reason) }
    deinit { driver.cancel("BLE coordinator owner released; no retry") }
}
