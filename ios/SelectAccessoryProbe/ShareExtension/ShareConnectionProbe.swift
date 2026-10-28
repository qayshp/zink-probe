import SwiftUI
import ExternalAccessory

/// Manual passive/firmware diagnostics plus full preflight and read-only recovery.
/// The native adapter permits connection-local setup, never print/clock/settings writes.
final class ShareConnectionProbe: NSObject, ObservableObject, StreamDelegate {
    @Published var accessories: [EAAccessory] = []
    @Published var active = false
    @Published var verifiedPrinter: VerifiedPrinter?
    @Published var report = "Share extension connection probe. No automatic session or writes.\n"
    private var session: EASession?
    private var timer: Timer?
    private var observers: [NSObjectProtocol] = []
    private var opened = Set<String>()
    private var identity = false
    private var wire = IdentityWire()
    private var received = 0
    private let protocolName = "com.hp.protocol.lifestyle"
    private let native = NativeAccessoryAdapter()
    private var nativeConnectionID: Int?
    #if targetEnvironment(simulator)
    private var simulation: AccessoryStreamDriver?
    private var simulationTimer: Timer?
    func simulatePreflight() {
        guard !active else { return }; verifiedPrinter = nil; active = true
        log("SIMULATED Share preflight; in-memory duplex only, no accessory session.")
        do {
            let pump = try AccessoryStreamPump(expectedFirmware:"G1L1FA2105AR",now:ProcessInfo.processInfo.systemUptime)
            simulation = AccessoryStreamDriver(pump:pump,io:ShareMemoryDuplex(),clock:{ ProcessInfo.processInfo.systemUptime }) { [weak self] result in
                guard let self else { return }; self.active = !result.terminal
                if result.terminal {
                    self.simulationTimer?.invalidate(); self.simulationTimer = nil
                    self.verifiedPrinter = result.verified
                    self.log("SIMULATED: \(result.result) RX=\(result.receivedBytes); TX=\(result.acceptedBytes). Real printer TX=0.")
                }
            }
            let timer = Timer(timeInterval:0.01,repeats:true) { [weak self] _ in self?.simulation?.tick() }
            simulationTimer = timer; RunLoop.main.add(timer,forMode:.common); simulation?.start()
        } catch { active = false; log("Simulation refused: \(error)") }
    }
    #endif

    override init() {
        super.init()
        for name in [NSNotification.Name.EAAccessoryDidConnect, .EAAccessoryDidDisconnect] {
            observers.append(NotificationCenter.default.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in self?.refresh() })
        }
        EAAccessoryManager.shared().registerForLocalNotifications()
        // Extension host lifecycle notifications, not UIApplication.shared.
        observers.append(NotificationCenter.default.addObserver(forName: Notification.Name.NSExtensionHostWillResignActive, object: nil, queue: .main) { [weak self] _ in self?.stop("Share host became inactive") })
        refresh()
    }
    deinit {
        #if targetEnvironment(simulator)
        simulationTimer?.invalidate(); simulation?.cancel("Simulation owner released")
        #endif
        native.stop("Share connection owner released")
        timer?.invalidate()
        for stream in [session?.inputStream as Stream?, session?.outputStream as Stream?].compactMap({ $0 }) {
            stream.delegate = nil; stream.close(); stream.remove(from: .main, forMode: .common)
        }
        for observer in observers { NotificationCenter.default.removeObserver(observer) }
    }
    private func log(_ message: String) {
        report += "\(ISO8601DateFormatter().string(from: Date())) \(message)\n"
        if report.count > 16000 { report = String(report.suffix(16000)) }
    }
    func refresh() {
        accessories = EAAccessoryManager.shared().connectedAccessories.filter {
            $0.modelNumber == "HPISPSLE" && $0.protocolStrings.contains(protocolName)
        }
        log("Select accessories visible to Share extension: \(accessories.count)")
        if let id = nativeConnectionID, !accessories.contains(where:{ $0.connectionID == id }) {
            verifiedPrinter = nil; nativeConnectionID = nil; native.stop("Accessory disconnected")
        }
        if let current = session?.accessory, !accessories.contains(where: { $0.connectionID == current.connectionID }) {
            stop("Accessory disconnected")
        }
    }
    func start(_ accessory: EAAccessory, readFirmware: Bool) {
        guard !active, accessory.isConnected, accessory.modelNumber == "HPISPSLE", accessory.protocolStrings.contains(protocolName) else { return }
        verifiedPrinter = nil
        wire = IdentityWire(); received = 0; opened = []; identity = readFirmware
        log("Share extension starting \(readFirmware ? "fixed firmware read" : "passive stream test") for HPISPSLE/lifestyle")
        guard let candidate = EASession(accessory: accessory, forProtocol: protocolName), let input = candidate.inputStream, let output = candidate.outputStream else {
            log("Session/streams unavailable in extension; cause not established."); return
        }
        session = candidate; active = true
        for stream: Stream in [input,output] { stream.delegate = self; stream.schedule(in: .main, forMode: .common); stream.open() }
        timer = Timer.scheduledTimer(withTimeInterval: 10, repeats: false) { [weak self] _ in self?.stop("10-second limit reached") }
    }
    func preflight(_ accessory: EAAccessory, expectedDeviceID: String? = nil) {
        guard !active else { return }
        verifiedPrinter = nil; active = true; nativeConnectionID = accessory.connectionID
        log("Share full read-only preflight started. Printing and persistent settings writes are blocked.")
        do {
            try native.preflight(accessory,expectedDeviceID:expectedDeviceID) { [weak self] result in
                guard let self else { return }
                self.active = !result.terminal
                if result.terminal {
                    self.verifiedPrinter = result.verified
                    self.log("\(result.result) Opened=\(result.streamsOpened); RX=\(result.receivedBytes); application TX=\(result.acceptedBytes). Identity bytes omitted.")
                }
            }
        } catch { active = false; log("Share preflight could not start: \(error)") }
    }
    func recover(_ accessory: EAAccessory, id: UUID) {
        guard !active else { return }
        verifiedPrinter = nil
        do {
            let journal = try JobJournal(url:LiveDraftStorage.storeURL())
            active = true; nativeConnectionID = accessory.connectionID
            try native.recover(accessory,id:id,journal:journal) { [weak self] result in
                guard let self else { return }; self.active = !result.terminal
                if result.terminal { self.log("\(result.result) RX=\(result.receivedBytes); application TX=\(result.acceptedBytes). No image resent.") }
            }
        } catch { active = false; log("Saved-job recovery refused: \(error)") }
    }
    func stream(_ stream: Stream, handle event: Stream.Event) {
        guard let current = session else { return }
        let direction = stream === current.inputStream ? "input" : "output"
        if event.contains(.errorOccurred) { stop("\(direction) error: \(stream.streamError?.localizedDescription ?? "unknown")"); return }
        if event.contains(.endEncountered) { stop("\(direction) ended"); return }
        if event.contains(.openCompleted) {
            opened.insert(direction); log("\(direction) openCompleted")
            if opened.count == 2 { log("Both streams opened inside Share extension.\(identity ? "" : " Application TX remains zero.")") }
        }
        if event.contains(.hasBytesAvailable), let input = current.inputStream, stream === input {
            var bytes = [UInt8](repeating: 0, count: min(512,4096-received))
            guard !bytes.isEmpty else { stop("Receive bound reached"); return }
            let count = input.read(&bytes, maxLength: bytes.count)
            guard count >= 0 else { stop("Input read failed"); return }
            if count > 0 {
                received += count
                log("RX \(count) bytes: " + bytes.prefix(count).map { String(format:"%02x",$0) }.joined())
                if identity {
                    do {
                        if let firmware = try wire.receive(Array(bytes.prefix(count))) {
                            log("Validated firmware \(firmware); matches accessory metadata: \(firmware == current.accessory?.firmwareRevision)")
                            stop("Firmware read complete in Share extension"); return
                        }
                    } catch { stop("Unexpected firmware response; no retry: \(error)"); return }
                }
                if received == 4096 { stop("Receive bound reached"); return }
            }
        }
        if identity, active, opened.count == 2, let output = current.outputStream, output.hasSpaceAvailable {
            do {
                let sent = try wire.send { bytes in bytes.withUnsafeBufferPointer { output.write($0.baseAddress!, maxLength: $0.count) } }
                if !sent.isEmpty { log("TX accepted \(sent.count) bytes: " + sent.map { String(format:"%02x",$0) }.joined()) }
            } catch { stop("Write failed; no retry: \(error)") }
        }
    }
    func stop(_ reason: String = "Stopped by user") {
        verifiedPrinter = nil
        #if targetEnvironment(simulator)
        simulationTimer?.invalidate(); simulationTimer = nil; simulation?.cancel(reason)
        #endif
        native.stop(reason)
        guard let current = session else { return }
        session = nil; timer?.invalidate(); timer = nil
        for stream in [current.inputStream as Stream?,current.outputStream as Stream?].compactMap({ $0 }) {
            stream.delegate = nil; stream.close(); stream.remove(from: .main, forMode: .common)
        }
        active = false
        log("\(reason). Opened=\(opened.sorted()); RX=\(received); application TX=\(wire.sent)")
    }
}

struct ShareConnectionView: View {
    @ObservedObject var probe: ShareConnectionProbe
    var body: some View {
        List {
            Section("Test connection from Share") {
                Text("Keep the Select awake nearby. Passive and firmware tests close within 10 seconds. Full preflight has a 60-second bound, checks identity, capabilities, status, queue and counters, and negotiates only a connection-local message limit. No printing or persistent settings changes.")
                Button("Refresh connected accessories") { probe.refresh() }.disabled(probe.active)
                #if targetEnvironment(simulator)
                Button("Simulate full preflight (no accessory)") { probe.simulatePreflight() }.disabled(probe.active)
                #endif
                if probe.accessories.isEmpty { Text("No Select visible here. Connect it using Select Probe or iPhone Bluetooth Settings, close that session, then return to Share and refresh. Pairing alone may not mean connected.") }
                ForEach(probe.accessories, id: \.connectionID) { accessory in
                    Text(accessory.name)
                    Button("Open streams without writing") { probe.start(accessory, readFirmware: false) }.buttonStyle(.bordered).disabled(probe.active)
                    Button("Read firmware once") { probe.start(accessory, readFirmware: true) }.buttonStyle(.borderedProminent).disabled(probe.active)
                    Button("Run full read-only preflight") { probe.preflight(accessory) }.buttonStyle(.bordered).disabled(probe.active)
                        .accessibilityIdentifier("share-full-preflight")
                }
                if probe.active { Button("Close test session") { probe.stop() } }
            }
            NavigationLink("Saved printer drafts") { SavedDraftsView(connection:probe) }
            Section("Report") {
                ShareLink("Share connection report", item: probe.report)
                Text(probe.report).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
            }
        }.buttonStyle(.borderless).navigationTitle("Share connection test")
        .onDisappear { probe.stop("Connection screen closed") }
    }
}

#if targetEnvironment(simulator)
private final class ShareMemoryDuplex: AccessoryDuplex {
    private let peer = SimulatedPrinter()
    private var closed = false
    var hasBytes: Bool { !closed && !peer.output.isEmpty }
    var hasSpace: Bool { !closed }
    func open(_ handler: @escaping (AccessoryIOEvent) -> Void) { handler(.opened(.input)); handler(.opened(.output)) }
    func read(maximum: Int) -> AccessoryRead {
        guard hasBytes else { return .wouldBlock }
        let count = min(maximum,37,peer.output.count), bytes = Array(peer.output.prefix(count))
        peer.output.removeFirst(count); return .bytes(bytes)
    }
    func write(_ bytes: [UInt8]) -> Int { peer.write(bytes,limit:13) }
    func close() { closed = true }
}

struct ShareAdapterTest: View {
    @StateObject private var connection = ShareConnectionProbe()
    var body: some View {
        SharePhotoFlow(initialData:SimulationUIFixture.png,connection:connection)
            .toolbar { ToolbarItem(placement:.primaryAction) {
                NavigationLink("Connection test") { ShareConnectionView(probe:connection) }
            } }
    }
}
#endif
