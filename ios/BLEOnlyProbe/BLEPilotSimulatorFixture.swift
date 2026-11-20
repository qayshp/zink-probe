#if ZINK_EXPERIMENTAL_BLE_PRINT && DEBUG && targetEnvironment(simulator)
import SwiftUI
import UIKit

/// A simulator-test-only peripheral. It drives the production coordinator
/// and clock session through BLE packets in memory, without CoreBluetooth.
struct BLEPilotSimulatorFixture {
    enum Scenario: String { case clock, unavailable, stoppedBeforeSend, uncertain }

    let storageRoot: URL
    let adapter: FixtureBLEAdapter
    let photo: Data
    let selection: SelectBLEProbe.CheckedSelection

    static func fromEnvironment() -> Self? {
        let environment = ProcessInfo.processInfo.environment
        guard let namespace = environment["ZINK_PILOT_FIXTURE_STORE"].flatMap(UUID.init(uuidString:)),
              let scenario = environment["ZINK_PILOT_FIXTURE_SCENARIO"].flatMap(Scenario.init(rawValue:)) else { return nil }
        let size = CGSize(width: 300, height: 450)
        let image = UIGraphicsImageRenderer(size: size).image { context in
            UIColor.systemTeal.setFill()
            context.fill(CGRect(origin: .zero, size: size))
            UIColor.systemOrange.setFill()
            context.fill(CGRect(x: 48, y: 63, width: 93, height: 177))
        }
        guard let photo = image.jpegData(compressionQuality: 0.92) else { return nil }
        let adapter = FixtureBLEAdapter(scenario: scenario)
        return Self(storageRoot: FileManager.default.temporaryDirectory.appendingPathComponent(namespace.uuidString),
                    adapter: adapter, photo: photo,
                    selection: .init(peripheralID: namespace, firmware: adapter.printer.firmware))
    }
}

final class FixtureBLEAdapter: BLEPilotAdapter {
    private let scenario: BLEPilotSimulatorFixture.Scenario
    let printer = SimulatedPrinter()
    private var duplex: BLESubmissionDuplex?
    private var timer: Timer?
    private var cancelSession: ((String) -> Void)?
    private var submissionAttempted = false
    private let clock = { ProcessInfo.processInfo.systemUptime }

    init(scenario: BLEPilotSimulatorFixture.Scenario) {
        self.scenario = scenario
        if scenario == .clock { printer.initialFlags = 1 }
    }

    var failureStage: BLESubmissionDuplex.FailureStage? { duplex?.failureStage }
    var transportCounters: JobJournal.PrintAttemptDiagnostics.GATT? {
        guard let duplex else { return nil }
        return .init(txQueuedBytes: duplex.txQueuedBytes, txAcknowledgedBytes: duplex.txAcknowledgedBytes,
                     writeCallbacks: duplex.writeCallbacks, rxBytes: duplex.rxBytes, protocolMTU: duplex.protocolMTU,
                     acknowledgementPeriod: duplex.acknowledgementPeriod)
    }
    var transportSummary: String { "Simulator fixture. No Bluetooth radio was used." }

    func preflight(peripheralID: UUID, expectedDeviceID: String?, expectedFirmware: String,
                   update: @escaping (AccessoryStreamPump) -> Void) throws {
        let io = FixturePacketIO(printer, unavailable: scenario == .unavailable)
        let session = try BLECoordinatorSession.preflight(io: io, expectedDeviceID: expectedDeviceID,
                                                          expectedFirmware: expectedFirmware, clock: clock, update: update)
        run(io, duplex: session.duplex, start: session.start, tick: session.tick, cancel: session.cancel)
    }

    func recover(peripheralID: UUID, id: UUID, journal: JobJournal,
                 update: @escaping (AccessoryStreamPump) -> Void) throws {
        let io = FixturePacketIO(printer)
        let session = try BLECoordinatorSession.recovery(io: io, id: id, journal: journal, clock: clock, update: update)
        run(io, duplex: session.duplex, start: session.start, tick: session.tick, cancel: session.cancel)
    }

    func submitOnce(peripheralID: UUID, reviewed: JobBinding, journal: JobJournal,
                    update: @escaping (AccessoryStreamPump) -> Void) throws {
        let io = FixturePacketIO(printer, unavailable: scenario == .stoppedBeforeSend && !submissionAttempted,
                                 dropStartReply: scenario == .uncertain)
        submissionAttempted = true
        let session = try BLECoordinatorSession.authorizedSubmission(io: io, reviewed: reviewed, journal: journal,
                                                                       clock: clock, pollInterval: 0.01, update: update)
        run(io, duplex: session.duplex, start: session.start, tick: session.tick, cancel: session.cancel)
    }

    func syncClock(peripheralID: UUID, expectedDeviceID: String, expectedFirmware: String,
                   update: @escaping (BLEClockSession.Outcome) -> Void) throws {
        let io = FixturePacketIO(printer)
        let session = try BLEClockSession(io: io, expectedDeviceID: expectedDeviceID, expectedFirmware: expectedFirmware,
                                          clock: clock, update: update)
        run(io, duplex: session.duplex, start: session.start, tick: session.tick, cancel: session.cancel)
    }

    func stop(_ reason: String) {
        cancelSession?(reason)
        releaseSession()
    }

    private func run(_ io: FixturePacketIO, duplex: BLESubmissionDuplex, start: () -> Void, tick: @escaping () -> Void,
                     cancel: @escaping (String) -> Void) {
        releaseSession()
        self.duplex = duplex
        cancelSession = cancel
        let timer = Timer(timeInterval: 0.01, repeats: true) { [weak self] _ in
            io.deliver()
            tick()
            if duplex.closed, self?.duplex === duplex { self?.releaseSession() }
        }
        self.timer = timer
        RunLoop.main.add(timer, forMode: .common)
        start()
    }

    private func releaseSession() {
        timer?.invalidate()
        timer = nil
        cancelSession = nil
    }
}

private final class FixturePacketIO: BLEPacketIO {
    private let printer: SimulatedPrinter
    private let unavailable: Bool
    private let dropStartReply: Bool
    private var codec = BLEPacketCodec()
    private var pending: [BLEPacketIOEvent] = []
    private var handler: ((BLEPacketIOEvent) -> Void)?

    init(_ printer: SimulatedPrinter, unavailable: Bool = false, dropStartReply: Bool = false) {
        self.printer = printer
        self.unavailable = unavailable
        self.dropStartReply = dropStartReply
    }

    func open(_ handler: @escaping (BLEPacketIOEvent) -> Void) {
        self.handler = handler
        pending.append(unavailable ? .failed : .ready(writeLimit: 512))
    }

    func write(_ packet: [UInt8]) -> Bool {
        do {
            let message = try codec.receive(packet, ackPeriod: 0, packetLimit: 512).message
            pending.append(.written)
            if let message {
                let response: [UInt8]
                switch message {
                case [10,1,0]: response = [11,1,2,2,0]
                case [8,1]: response = [9,1] + SimulatedPrinter.le(printer.initialFlags, 4)
                case _ where message.first == 24:
                    printer.initialFlags = 0
                    response = [25]
                default: response = printer.respond(message)
                }
                if dropStartReply && message.first == 12 {
                    pending.append(.ended)
                } else {
                    let notifications = try BLEPacketCodec.fragments(response, packetLimit: 512)
                    pending += notifications.map(BLEPacketIOEvent.notification)
                }
            }
            return true
        } catch {
            pending.removeAll()
            return false
        }
    }

    func deliver() {
        let events = pending
        pending.removeAll()
        for event in events { handler?(event) }
    }

    func close() {
        pending.removeAll()
        handler = nil
    }
}
#endif
