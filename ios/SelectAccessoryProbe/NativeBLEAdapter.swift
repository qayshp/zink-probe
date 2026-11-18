import Foundation
import CoreBluetooth

/// The radio boundary. Constructing this object does not create a central
/// manager; only an explicit read-only operation opens it. Each instance owns
/// one selected peripheral and is permanently closed after any terminal event.
private final class NativeBLEPacketIO: NSObject, BLEPacketIO, CBCentralManagerDelegate, CBPeripheralDelegate {
    private enum Stage { case idle, waiting, connecting, services, characteristics, subscribing, ready, closed }
    private static let serviceID = CBUUID(string: "6822d239-7b61-4718-bdc1-189221946209")
    private static let txID = CBUUID(string: "6822d239-7b61-4718-bdc1-de55b3f9051e")
    private static let rxID = CBUUID(string: "6822d239-7b61-4718-bdc1-772fa9983658")
    private let selectedID: UUID
    private var stage: Stage = .idle
    private var central: CBCentralManager?
    private var peripheral: CBPeripheral?
    private var service: CBService?
    private var tx: CBCharacteristic?
    private var rx: CBCharacteristic?
    private var handler: ((BLEPacketIOEvent) -> Void)?
    private var writeOutstanding = false
    private var deadline: TimeInterval = 0
    private var now: TimeInterval { ProcessInfo.processInfo.systemUptime }

    init(peripheralID: UUID) { selectedID = peripheralID; super.init() }

    func open(_ handler: @escaping (BLEPacketIOEvent) -> Void) {
        precondition(Thread.isMainThread)
        guard stage == .idle else { handler(.failed); return }
        self.handler = handler; stage = .waiting; deadline = now + 30
        central = CBCentralManager(delegate: self, queue: .main)
    }
    func tick() {
        precondition(Thread.isMainThread)
        guard stage != .idle, stage != .closed, stage != .ready else { return }
        if now >= deadline { fail() }
    }
    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        guard central === self.central, stage != .closed else { return }
        guard central.state == .poweredOn else {
            if central.state == .unknown || central.state == .resetting { return }
            fail(); return
        }
        guard stage == .waiting else { return }
        // The peripheral UUID is routing only. Fresh protocol identity/model
        // checks in the pump must still match the saved canonical device ID.
        let matches = central.retrievePeripherals(withIdentifiers: [selectedID]).filter { $0.identifier == selectedID }
        guard matches.count == 1 else { fail(); return }
        let selected = matches[0]
        peripheral = selected; selected.delegate = self
        stage = .connecting; deadline = now + 10
        central.connect(selected, options: nil)
    }
    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        guard central === self.central, peripheral === self.peripheral, stage == .connecting else { return }
        stage = .services; deadline = now + 10
        peripheral.discoverServices([Self.serviceID])
    }
    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        guard central === self.central, peripheral === self.peripheral, stage != .closed else { return }
        fail()
    }
    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        guard central === self.central, peripheral === self.peripheral, stage != .closed else { return }
        let callback = handler; close(); callback?(.ended)
    }
    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        guard peripheral === self.peripheral, stage == .services else { return }
        let matches = (peripheral.services ?? []).filter { $0.uuid == Self.serviceID }
        guard error == nil, matches.count == 1 else { fail(); return }
        service = matches[0]; stage = .characteristics; deadline = now + 10
        peripheral.discoverCharacteristics([Self.txID, Self.rxID], for: matches[0])
    }
    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        guard peripheral === self.peripheral, service === self.service, stage == .characteristics else { return }
        let txs = (service.characteristics ?? []).filter { $0.uuid == Self.txID }
        let rxs = (service.characteristics ?? []).filter { $0.uuid == Self.rxID }
        guard error == nil, txs.count == 1, rxs.count == 1,
              txs[0].properties.contains(.write),
              rxs[0].properties.contains(.notify) || rxs[0].properties.contains(.indicate) else { fail(); return }
        tx = txs[0]; rx = rxs[0]
        stage = .subscribing; deadline = now + 10
        peripheral.setNotifyValue(true, for: rxs[0])
    }
    func peripheral(_ peripheral: CBPeripheral, didUpdateNotificationStateFor characteristic: CBCharacteristic, error: Error?) {
        guard peripheral === self.peripheral, characteristic === rx, stage != .closed else { return }
        guard stage == .subscribing, error == nil, characteristic.isNotifying else { fail(); return }
        stage = .ready
        handler?(.ready(writeLimit: peripheral.maximumWriteValueLength(for: .withResponse)))
    }
    func write(_ packet: [UInt8]) -> Bool {
        precondition(Thread.isMainThread)
        guard stage == .ready, !writeOutstanding, let peripheral, let tx,
              !packet.isEmpty, packet.count <= peripheral.maximumWriteValueLength(for: .withResponse) else { return false }
        writeOutstanding = true
        peripheral.writeValue(Data(packet), for: tx, type: .withResponse)
        return true
    }
    func peripheral(_ peripheral: CBPeripheral, didWriteValueFor characteristic: CBCharacteristic, error: Error?) {
        guard peripheral === self.peripheral, characteristic === tx, stage != .closed else { return }
        guard stage == .ready, writeOutstanding, error == nil else { fail(); return }
        writeOutstanding = false; handler?(.written)
    }
    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        guard peripheral === self.peripheral, characteristic === rx, stage != .closed else { return }
        guard stage == .ready, error == nil, let value = characteristic.value, !value.isEmpty else { fail(); return }
        handler?(.notification(Array(value)))
    }
    private func fail() {
        let callback = handler; close(); callback?(.failed)
    }
    func close() {
        precondition(Thread.isMainThread)
        guard stage != .closed else { return }
        stage = .closed; handler = nil; writeOutstanding = false
        peripheral?.delegate = nil
        if let peripheral { central?.cancelPeripheralConnection(peripheral) }
        central?.delegate = nil; central = nil
        peripheral = nil; service = nil; tx = nil; rx = nil
    }
    deinit { if stage != .closed { close() } }
}

/// Main-run-loop native BLE owner used by the app and Share read-only preflight.
/// Live operations can only compose a read-only duplex.
/// The existing accessory submission route is unchanged.
final class NativeBLEAdapter {
    private var session: BLECoordinatorSession?
    private var packetIO: NativeBLEPacketIO?
    private var timer: Timer?
    private let clock = { ProcessInfo.processInfo.systemUptime }
    var active: Bool { session.map { !$0.closed } ?? false }
    /// Packet-format counters, not an over-the-air capture. Never includes
    /// peripheral UUIDs, protocol identity, names or raw response bytes.
    var transportSummary: String {
        guard let ble = session?.duplex else { return "No BLE adapter session started." }
        return "GATT packets: TX queued=\(ble.txQueuedBytes), acknowledged=\(ble.txAcknowledgedBytes), write callbacks=\(ble.writeCallbacks), RX=\(ble.rxBytes); protocol MTU=\(ble.protocolMTU), ACK period=\(ble.acknowledgementPeriod)."
    }

    func preflight(peripheralID: UUID, expectedDeviceID: String? = nil, expectedFirmware: String,
                   update: @escaping (AccessoryStreamPump) -> Void) throws {
        precondition(Thread.isMainThread)
        guard !active else { throw JobJournal.Failure.blocked }
        let io = NativeBLEPacketIO(peripheralID: peripheralID)
        let candidate = try BLECoordinatorSession.preflight(io: io, expectedDeviceID: expectedDeviceID,
            expectedFirmware: expectedFirmware, clock: clock, update: observer(update))
        start(io: io, session: candidate)
    }
    /// Uses the same journal/canonical protocol identity as the accessory route.
    /// Recovery never reloads a JPEG or reconstructs an upload plan.
    func recover(peripheralID: UUID, id: UUID, journal: JobJournal,
                 update: @escaping (AccessoryStreamPump) -> Void) throws {
        precondition(Thread.isMainThread)
        guard !active else { throw JobJournal.Failure.blocked }
        let io = NativeBLEPacketIO(peripheralID: peripheralID)
        let candidate = try BLECoordinatorSession.recovery(io: io, id: id, journal: journal,
            clock: clock, update: observer(update))
        start(io: io, session: candidate)
    }
    /// No runtime enable flag. Refuses before permit reservation, job claim,
    /// central-manager creation or any GATT write, even for a valid saved draft.
    func submitOnce(peripheralID: UUID, reviewed: JobBinding, journal: JobJournal,
                    update: @escaping (AccessoryStreamPump) -> Void) throws {
        try BLESubmissionAvailability.requireLiveSubmission()
        precondition(Thread.isMainThread)
        guard !active else { throw JobJournal.Failure.blocked }
        let io = NativeBLEPacketIO(peripheralID: peripheralID)
        let candidate = try BLECoordinatorSession.authorizedSubmission(io: io, reviewed: reviewed,
            journal: journal, clock: clock, update: observer(update))
        start(io: io, session: candidate)
    }
    private func observer(_ update: @escaping (AccessoryStreamPump) -> Void) -> (AccessoryStreamPump) -> Void {
        { [weak self] result in
            if result.terminal { self?.timer?.invalidate(); self?.timer = nil }
            update(result)
        }
    }
    private func start(io: NativeBLEPacketIO, session: BLECoordinatorSession) {
        precondition(Thread.isMainThread)
        packetIO = io; self.session = session
        let tick = Timer(timeInterval: 0.1, repeats: true) { [weak self] _ in
            self?.packetIO?.tick(); self?.session?.tick()
        }
        timer = tick; RunLoop.main.add(tick, forMode: .common)
        session.start()
    }
    func stop(_ reason: String) {
        precondition(Thread.isMainThread)
        timer?.invalidate(); timer = nil; session?.cancel(reason)
    }
    deinit { timer?.invalidate(); session?.cancel("BLE owner released; no retry") }
}
