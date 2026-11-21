import CoreBluetooth
import SwiftUI

/// A diagnostic-only CoreBluetooth owner shared by the app and Share target.
/// Constructing the view does not construct a central manager or ask for access.
/// The fixed BLEReadOnlyCheck is the sole source of application writes.
final class SelectBLEProbe: NSObject, ObservableObject, CBCentralManagerDelegate, CBPeripheralDelegate {
    struct Candidate: Identifiable {
        let id: UUID
        let name: String
        let rssi: Int?
        let alreadyConnected: Bool
    }
    /// Routing metadata from a completed diagnostic. This does not bind a saved
    /// job or authorize a new connection; the adapter still reads protocol ID.
    struct CheckedSelection: Equatable {
        let peripheralID: UUID
        let firmware: String
    }
    private enum Activity { case idle, waiting, scanning, connecting, services, characteristics, subscribing, checking }
    private static let service = CBUUID(string: "6822d239-7b61-4718-bdc1-189221946209")
    private static let tx = CBUUID(string: "6822d239-7b61-4718-bdc1-de55b3f9051e")
    private static let rx = CBUUID(string: "6822d239-7b61-4718-bdc1-772fa9983658")
    @Published private(set) var candidates: [Candidate] = []
    @Published private(set) var active = false
    @Published private(set) var status = "Ready for an explicit BLE scan."
    @Published private(set) var report: String
    @Published private(set) var checkedSelection: CheckedSelection? = nil
    private let context: String
    private var activity: Activity = .idle
    private var central: CBCentralManager?
    private var peripherals: [UUID: CBPeripheral] = [:]
    private var selected: CBPeripheral?
    private var tx: CBCharacteristic?
    private var rx: CBCharacteristic?
    private var core: BLEReadOnlyCheck?
    private var timer: Timer?
    private var deadline = 0.0
    private var overallDeadline = 0.0
    private var writeInFlight = false
    private var queuedTX = 0
    private var acknowledgedTX = 0
    private var receivedRX = 0
    private var completedWrites = 0
    private var writeLength = 0
    private var phase = ""
    private var now: TimeInterval { ProcessInfo.processInfo.systemUptime }

    init(context: String) {
        self.context = context
        report = "CoreBluetooth read-only check · \(context). No automatic scan, connection or writes.\n"
        super.init()
    }

    func scan() {
        guard !active else { return }
        checkedSelection = nil
        releaseConnection()
        central?.delegate = nil
        central = nil
        peripherals = [:]; candidates = []; core = nil
        queuedTX = 0; acknowledgedTX = 0; receivedRX = 0; completedWrites = 0
        active = true; activity = .waiting; status = "Waiting for Bluetooth access…"
        deadline = now + 30; overallDeadline = now + 45
        log("Explicit service-filtered scan requested in \(context). Bluetooth authorization raw=\(CBManager.authorization.rawValue).")
        central = CBCentralManager(delegate: self, queue: .main,
                                   options: [CBCentralManagerOptionShowPowerAlertKey: false])
        startTimer()
    }

    func connect(_ candidate: Candidate) {
        guard !active, let central, central.state == .poweredOn,
              let peripheral = peripherals[candidate.id],
              peripheral.state == .disconnected || peripheral.state == .connected else { return }
        checkedSelection = nil
        selected = peripheral; peripheral.delegate = self
        core = nil; tx = nil; rx = nil; phase = ""
        queuedTX = 0; acknowledgedTX = 0; receivedRX = 0; completedWrites = 0
        writeLength = 0; writeInFlight = false
        active = true; activity = .connecting; deadline = now + 10; overallDeadline = now + 90
        status = "Connecting over BLE…"
        log("Explicit BLE check requested for one selected candidate; no External Accessory session.")
        startTimer()
        central.connect(peripheral, options: nil)
    }

    func stop(_ reason: String = "Stopped by user") {
        guard active else { return }
        core?.stop()
        finish(reason)
    }

    private func log(_ message: String) {
        report += "\(ISO8601DateFormatter().string(from: Date())) \(message)\n"
        if report.count > 64000 { report = String(report.suffix(64000)) }
    }

    private func errorCode(_ error: Error?, fallback: String) -> String {
        guard let error else { return fallback }
        let value = error as NSError
        // Framework descriptions may embed a peripheral name or identifier.
        return "\(value.domain) code \(value.code)"
    }

    private func startTimer() {
        timer?.invalidate()
        let tick = Timer(timeInterval: 0.1, repeats: true) { [weak self] _ in self?.tick() }
        timer = tick; RunLoop.main.add(tick, forMode: .common)
    }

    private func tick() {
        guard active else { return }
        if activity == .scanning, now >= deadline { endScan(); return }
        if now >= overallDeadline { stop("Overall diagnostic time limit reached; no retry"); return }
        if activity == .checking {
            do { try core?.check(now: now); drive() }
            catch { stop("BLE protocol stopped: \(error); no retry") }
        } else if now >= deadline { stop("Bluetooth setup timed out at \(status); no retry") }
    }

    private func releaseConnection() {
        central?.stopScan()
        selected?.delegate = nil
        if let selected { central?.cancelPeripheralConnection(selected) }
        selected = nil; tx = nil; rx = nil; writeInFlight = false
    }

    private func finish(_ reason: String) {
        guard active else { return }
        active = false; activity = .idle
        timer?.invalidate(); timer = nil
        status = reason
        log("\(reason). GATT TX queued=\(queuedTX), acknowledged=\(acknowledgedTX), write callbacks=\(completedWrites), RX=\(receivedRX). No job allocation or image data sent.")
        releaseConnection()
        // A fresh manager/scan is required before another attempt. This prevents
        // a late disconnect callback from an old connection ending a new check.
        candidates = []; peripherals = [:]
    }

    private func endScan() {
        central?.stopScan(); activity = .idle; active = false
        timer?.invalidate(); timer = nil
        status = candidates.isEmpty
            ? "No Select found. Wake the printer, keep it near this iPhone, then scan again."
            : "Choose a printer for the read-only check."
        log("Scan ended: \(candidates.count) candidate(s). Application TX=0. An empty scan does not establish incompatibility.")
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        guard central === self.central, active else { return }
        guard central.state == .poweredOn else {
            if central.state == .unknown || central.state == .resetting { return }
            let message: String
            switch central.state {
            case .unauthorized: message = "Bluetooth access is denied or restricted. Check Settings → Privacy & Security → Bluetooth."
            case .poweredOff: message = "iPhone Bluetooth is off. Enable it in Settings before scanning again."
            case .unsupported: message = "CoreBluetooth is unavailable on this device."
            default: message = "Bluetooth is unavailable (state \(central.state.rawValue))."
            }
            stop(message); return
        }
        guard activity == .waiting else { return }
        activity = .scanning; status = "Scanning for 10 seconds…"; deadline = now + 10
        for peripheral in central.retrieveConnectedPeripherals(withServices: [Self.service]) {
            add(peripheral, rssi: nil, connected: true)
        }
        central.scanForPeripherals(withServices: [Self.service],
                                  options: [CBCentralManagerScanOptionAllowDuplicatesKey: false])
        log("Bluetooth powered on; 10-second Select-service scan started. Already-connected peripherals are also considered.")
    }

    private func add(_ peripheral: CBPeripheral, rssi: Int?, connected: Bool) {
        guard peripherals.count < 32 || peripherals[peripheral.identifier] != nil else { return }
        peripherals[peripheral.identifier] = peripheral
        let item = Candidate(id: peripheral.identifier,
                             name: String((peripheral.name ?? "Select service candidate").prefix(60)),
                             rssi: rssi, alreadyConnected: connected)
        if let index = candidates.firstIndex(where: { $0.id == item.id }) { candidates[index] = item }
        else { candidates.append(item) }
    }

    func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral,
                        advertisementData: [String: Any], rssi RSSI: NSNumber) {
        guard central === self.central, activity == .scanning else { return }
        if let data = advertisementData[CBAdvertisementDataServiceDataKey] as? [CBUUID: Data],
           let model = data[Self.service], model.count >= 2,
           Array(model.prefix(2)) != [0xd3, 0x48] { return }
        add(peripheral, rssi: RSSI.intValue == 127 ? nil : RSSI.intValue, connected: false)
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        guard central === self.central, peripheral === selected, activity == .connecting else { return }
        activity = .services; status = "Discovering the Select BLE service…"; deadline = now + 10
        peripheral.discoverServices([Self.service])
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        guard central === self.central, peripheral === selected, active else { return }
        stop("BLE connection failed: \(errorCode(error, fallback: "no additional detail")); no retry")
    }

    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        guard central === self.central, peripheral === selected, active else { return }
        stop("BLE disconnected: \(errorCode(error, fallback: "connection ended")); no retry")
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        guard peripheral === selected, activity == .services else { return }
        guard error == nil, let service = peripheral.services?.first(where: { $0.uuid == Self.service }) else {
            stop("Select service discovery failed: \(errorCode(error, fallback: "service missing"))"); return
        }
        activity = .characteristics; status = "Discovering the two protocol characteristics…"; deadline = now + 10
        // Never discover/read the pairing/control characteristic in this check.
        peripheral.discoverCharacteristics([Self.tx, Self.rx], for: service)
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        guard peripheral === selected, activity == .characteristics, service.uuid == Self.service else { return }
        guard error == nil, let chars = service.characteristics,
              let tx = chars.first(where: { $0.uuid == Self.tx }), tx.properties.contains(.write),
              let rx = chars.first(where: { $0.uuid == Self.rx }),
              rx.properties.contains(.notify) || rx.properties.contains(.indicate) else {
            stop("Required write-with-response / notification characteristics unavailable"); return
        }
        self.tx = tx; self.rx = rx
        activity = .subscribing; status = "Subscribing to protocol replies…"; deadline = now + 10
        peripheral.setNotifyValue(true, for: rx)
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateNotificationStateFor characteristic: CBCharacteristic, error: Error?) {
        guard peripheral === selected, characteristic === rx, activity == .subscribing else { return }
        guard error == nil, characteristic.isNotifying else {
            stop("BLE notification subscription failed: \(errorCode(error, fallback: "not enabled"))"); return
        }
        do {
            let limit = peripheral.maximumWriteValueLength(for: .withResponse)
            core = try BLEReadOnlyCheck(platformWriteLimit: limit, now: now)
            log("RX subscribed. Platform write-with-response limit=\(limit) bytes. Fixed read-only sequence starting.")
            activity = .checking; drive()
        } catch { stop("BLE protocol could not start: \(error)") }
    }

    private func drive() {
        guard activity == .checking, let peripheral = selected, let tx else { return }
        do {
            if core?.phase != phase {
                phase = core?.phase ?? ""
                status = "Checking: \(phase)"; log(status)
            }
            if core?.complete == true, !writeInFlight {
                let selection = core?.result.map { CheckedSelection(peripheralID: peripheral.identifier, firmware: $0.firmware) }
                finish(core!.summary)
                checkedSelection = selection
                return
            }
            guard !writeInFlight, let packet = try core?.nextWrite(now: now) else { return }
            guard !packet.isEmpty, packet.count <= peripheral.maximumWriteValueLength(for: .withResponse) else {
                stop("Refused packet exceeding the platform write limit"); return
            }
            writeInFlight = true; writeLength = packet.count; queuedTX += packet.count
            peripheral.writeValue(Data(packet), for: tx, type: .withResponse)
        } catch { stop("BLE protocol stopped: \(error); no retry") }
    }

    func peripheral(_ peripheral: CBPeripheral, didWriteValueFor characteristic: CBCharacteristic, error: Error?) {
        guard peripheral === selected, characteristic === tx, activity == .checking else { return }
        guard error == nil, writeInFlight else {
            stop("BLE write failed or callback was unexpected: \(errorCode(error, fallback: "unexpected callback")); no retry"); return
        }
        writeInFlight = false; acknowledgedTX += writeLength; completedWrites += 1; writeLength = 0
        do { try core?.didWrite(now: now); drive() }
        catch { stop("BLE write completion stopped: \(error); no retry") }
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        guard peripheral === selected, characteristic === rx, activity == .checking else { return }
        guard error == nil, let data = characteristic.value else {
            stop("BLE notification failed: \(errorCode(error, fallback: "no data"))"); return
        }
        receivedRX += data.count
        do { try core?.receive(Array(data), now: now); drive() }
        catch { stop("BLE reply rejected: \(error); no retry") }
    }
}

struct BLEProbeView: View {
    @StateObject private var probe: SelectBLEProbe
    @Environment(\.scenePhase) private var scenePhase
    init(context: String) { _probe = StateObject(wrappedValue: SelectBLEProbe(context: context)) }
    var body: some View {
        List {
            Section("Independent BLE connection") {
                Text("This check uses CoreBluetooth directly. Scan, choose your Select, then read its identity, status and capabilities. No photo or print job is sent.")
                Text("Keep the Select awake nearby and close any active printer test first. BLE access may prompt for permission or system-managed pairing. An empty scan or failed connection does not identify the cause.").font(.caption)
                Button("Scan for Select over BLE") { probe.scan() }
                    .disabled(probe.active).accessibilityIdentifier("ble-scan")
                Text(probe.status).accessibilityIdentifier("ble-status")
                if probe.active {
                    ProgressView()
                    Button("Stop BLE check") { probe.stop() }.accessibilityIdentifier("ble-stop")
                }
            }
            Section("BLE candidates") {
                ForEach(probe.candidates) { item in
                    VStack(alignment: .leading) {
                        Text(item.name).font(.headline)
                        if let rssi = item.rssi { Text("Signal: \(rssi) dBm").font(.caption) }
                        if item.alreadyConnected { Text("Already connected to this iPhone").font(.caption) }
                        Button("Run read-only BLE check") { probe.connect(item) }
                            .disabled(probe.active).accessibilityIdentifier("ble-read-only")
                    }
                }
            }
            Section("Diagnostic report") {
                ShareLink("Share BLE report", item: probe.report)
                Text("The report includes firmware and status but omits device identifiers and raw identity frames.").font(.caption)
                Text(probe.report).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
            }
        }
        .buttonStyle(.borderless)
        .navigationTitle("Read-only BLE check")
        .onDisappear { probe.stop("BLE screen closed") }
        .onChange(of: scenePhase) { phase in
            // Permission/system pairing prompts may temporarily make the scene
            // inactive. Backgrounding or dismissal still cancels the check.
            if phase == .background { probe.stop("BLE screen entered the background") }
        }
        .onReceive(NotificationCenter.default.publisher(for: .NSExtensionHostDidEnterBackground)) { _ in
            probe.stop("Share host entered the background")
        }
    }
}
