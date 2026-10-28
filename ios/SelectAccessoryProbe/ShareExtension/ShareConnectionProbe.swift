import SwiftUI
import ExternalAccessory

/// Native stream owner for passive tests and IdentityWire's fixed firmware read.
/// It never drives the separate upload simulation or emits clock/setup requests.
final class ShareConnectionProbe: NSObject, ObservableObject, StreamDelegate {
    @Published var accessories: [EAAccessory] = []
    @Published var active = false
    @Published var report = "Share extension connection probe. No automatic session or writes.\n"
    private var session: EASession?
    private var timer: Timer?
    private var observers: [NSObjectProtocol] = []
    private var opened = Set<String>()
    private var identity = false
    private var wire = IdentityWire()
    private var received = 0
    private let protocolName = "com.hp.protocol.lifestyle"

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
        if let current = session?.accessory, !accessories.contains(where: { $0.connectionID == current.connectionID }) {
            stop("Accessory disconnected")
        }
    }
    func start(_ accessory: EAAccessory, readFirmware: Bool) {
        guard !active, accessory.isConnected, accessory.modelNumber == "HPISPSLE", accessory.protocolStrings.contains(protocolName) else { return }
        wire = IdentityWire(); received = 0; opened = []; identity = readFirmware
        log("Share extension starting \(readFirmware ? "fixed firmware read" : "passive stream test") for HPISPSLE/lifestyle")
        guard let candidate = EASession(accessory: accessory, forProtocol: protocolName), let input = candidate.inputStream, let output = candidate.outputStream else {
            log("Session/streams unavailable in extension; cause not established."); return
        }
        session = candidate; active = true
        for stream: Stream in [input,output] { stream.delegate = self; stream.schedule(in: .main, forMode: .common); stream.open() }
        timer = Timer.scheduledTimer(withTimeInterval: 10, repeats: false) { [weak self] _ in self?.stop("10-second limit reached") }
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
                Text("Keep the Select awake nearby. These tests run inside this Share extension. Passive sends no application bytes; firmware sends one fixed read request. Each closes within 10 seconds. No printing or settings changes.")
                Button("Refresh connected accessories") { probe.refresh() }.disabled(probe.active)
                if probe.accessories.isEmpty { Text("No Select visible here. Connect it using Select Probe or iPhone Bluetooth Settings, close that session, then return to Share and refresh. Pairing alone may not mean connected.") }
                ForEach(probe.accessories, id: \.connectionID) { accessory in
                    Text(accessory.name)
                    Button("Open streams without writing") { probe.start(accessory, readFirmware: false) }.buttonStyle(.bordered).disabled(probe.active)
                    Button("Read firmware once") { probe.start(accessory, readFirmware: true) }.buttonStyle(.borderedProminent).disabled(probe.active)
                }
                if probe.active { Button("Close test session") { probe.stop() } }
            }
            Section("Report") {
                ShareLink("Share connection report", item: probe.report)
                Text(probe.report).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
            }
        }.navigationTitle("Share connection test")
        .onDisappear { probe.stop("Connection screen closed") }
    }
}
