import SwiftUI
import ExternalAccessory

// Only one fixed firmware-identity request is permitted on the Select lifestyle session.
// Opening streams necessarily performs system-managed accessory negotiation.
final class Probe: NSObject, ObservableObject, StreamDelegate {
    static let protocols = ["com.hp.protocol.bahama", "com.hp.protocol.lifestyle",
                            "com.hp.protocol.maui", "com.hp.protocol"]
    @Published var accessories: [EAAccessory] = []
    @Published var report = ""
    @Published var active = false
    private var identityMode = false
    private var wire = IdentityWire()
    private var session: EASession?
    private var timer: Timer?
    private var opened = Set<String>()
    private var received = 0
    private let limit = 4096
    private var observers: [NSObjectProtocol] = []

    override init() {
        super.init()
        for name in [NSNotification.Name.EAAccessoryDidConnect, .EAAccessoryDidDisconnect] {
            observers.append(NotificationCenter.default.addObserver(forName: name, object: nil,
                queue: .main) { [weak self] _ in
                    self?.refresh()
                })
        }
        EAAccessoryManager.shared().registerForLocalNotifications()
        log("Read-only probe started. Application bytes transmitted: 0. No automatic session attempt.")
        refresh()
    }

    func log(_ message: String) {
        let line = "\(ISO8601DateFormatter().string(from: Date())) \(message)"
        report += line + "\n"
        print(line)
        // Bounded local report; never uploads automatically and omits accessory serial numbers.
        if report.count > 64000 { report = String(report.suffix(64000)) }
        if let root = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first {
            try? report.write(to: root.appendingPathComponent("probe.txt"), atomically: true, encoding: .utf8)
        }
    }

    func refresh() {
        accessories = EAAccessoryManager.shared().connectedAccessories
        log("Connected accessories visible to this app: \(accessories.count)")
        for a in accessories {
            log("Accessory name=\(a.name), manufacturer=\(a.manufacturer), model=\(a.modelNumber), firmware=\(a.firmwareRevision), hardware=\(a.hardwareRevision), protocols=\(a.protocolStrings)")
        }
        if let current = session?.accessory,
           !accessories.contains(where: { $0.connectionID == current.connectionID }) {
            stop("Accessory disconnected")
        }
    }

    func picker() {
        log("Opening Apple's accessory picker; this can pair/connect an accessory.")
        EAAccessoryManager.shared().showBluetoothAccessoryPicker(withNameFilter: NSPredicate(format: "SELF CONTAINS[c] %@", "sprocket")) { [weak self] error in
            DispatchQueue.main.async {
                self?.log("Picker finished: \(error?.localizedDescription ?? "no error")")
                self?.refresh()
            }
        }
    }

    func start(_ accessory: EAAccessory, protocolName: String, readIdentity: Bool = false) {
        guard !active else { return }
        guard accessory.isConnected, Self.protocols.contains(protocolName),
              accessory.protocolStrings.contains(protocolName) else {
            log("Refused: protocol must be declared here and currently advertised by the accessory.")
            return
        }
        if readIdentity && (accessory.modelNumber != "HPISPSLE" || protocolName != "com.hp.protocol.lifestyle") {
            log("Refused: identity request is restricted to HPISPSLE / lifestyle.")
            return
        }
        identityMode = readIdentity
        wire = IdentityWire()
        received = 0
        opened = []
        log("Attempting EASession for \(accessory.name): \(protocolName)")
        guard let candidate = EASession(accessory: accessory, forProtocol: protocolName) else {
            log("EASession returned nil. Cause not established: authorization, competing app, or connection state may be relevant.")
            return
        }
        guard let input = candidate.inputStream, let output = candidate.outputStream else {
            log("Session object created but missing stream(s); not an open connection.")
            return
        }
        session = candidate
        active = true
        log(identityMode ? "Session created; will send one fixed firmware identity request once both streams open." : "Session created; passive observation only, no application writes.")
        for stream: Stream in [input, output] {
            stream.delegate = self
            stream.schedule(in: .main, forMode: .common)
            stream.open()
        }
        timer = Timer.scheduledTimer(withTimeInterval: 10, repeats: false) { [weak self] _ in
            self?.stop("10-second observation complete")
        }
    }

    func stream(_ aStream: Stream, handle eventCode: Stream.Event) {
        guard let current = session else { return }
        let direction = aStream === current.inputStream ? "input" : "output"
        if eventCode.contains(.openCompleted) {
            opened.insert(direction)
            log("\(direction) openCompleted")
            if opened.count == 2 { log("Both streams opened. This proves session access, not printer protocol compatibility or print support.") }
        }
        if eventCode.contains(.hasBytesAvailable), let input = aStream as? InputStream {
            var buffer = [UInt8](repeating: 0, count: min(512, limit - received))
            guard !buffer.isEmpty else { stop("Receive limit reached"); return }
            let count = input.read(&buffer, maxLength: buffer.count)
            if count > 0 {
                received += count
                log("RX \(count) bytes: " + buffer.prefix(count).map { String(format: "%02x", $0) }.joined())
                if identityMode {
                    do {
                        if let firmware = try wire.receive(Array(buffer.prefix(count))) {
                            log("Validated HP+ firmware response: \(firmware); matches accessory metadata: \(firmware == current.accessory?.firmwareRevision)")
                            stop("Identity request complete")
                            return
                        }
                    } catch { stop("Unexpected/malformed identity response; no retry: \(error)"); return }
                }
                if received >= limit { stop("Receive limit reached") }
            } else if count < 0 { stop("Input read error: \(input.streamError?.localizedDescription ?? "unknown")") }
        }
        if eventCode.contains(.errorOccurred) {
            stop("\(direction) error: \(aStream.streamError?.localizedDescription ?? "unknown")")
        } else if eventCode.contains(.endEncountered) { stop("\(direction) ended") }
        if identityMode, active, opened.count == 2,
           let output = current.outputStream, output.hasSpaceAvailable {
            do {
                let accepted = try wire.send { bytes in
                    bytes.withUnsafeBufferPointer { output.write($0.baseAddress!, maxLength: $0.count) }
                }
                if !accepted.isEmpty {
                    log("TX accepted \(accepted.count) bytes: " + accepted.map { String(format: "%02x", $0) }.joined())
                }
            } catch { stop("Identity write failed; no retry: \(error)") }
        }
    }

    func stop(_ reason: String = "Stopped by user") {
        guard let current = session else { return }
        timer?.invalidate()
        timer = nil
        session = nil
        for stream in [current.inputStream as Stream?, current.outputStream as Stream?].compactMap({ $0 }) {
            stream.delegate = nil
            stream.close()
            stream.remove(from: .main, forMode: .common)
        }
        active = false
        log("\(reason). Opened streams=\(opened.sorted()); RX=\(received); application TX=\(wire.sent).")
    }
}

@main
struct SelectAccessoryProbeApp: App {
    @StateObject private var probe = Probe()
    @Environment(\.scenePhase) private var phase
    var body: some Scene {
        WindowGroup {
            NavigationStack {
                List {
                    Section {
                        Text("No printing or settings changes. Passive tests send nothing; Read firmware sends one fixed identity request. Sessions last at most 10 seconds. Opening a connection may wake the printer.")
                        Button("Refresh connected accessories") { probe.refresh() }
                        Button("Find Sprocket with Apple picker") { probe.picker() }.disabled(probe.active)
                        if probe.active { Button("Close session now") { probe.stop() } }
                    }
                    Section("Visible accessories") {
                        if probe.accessories.isEmpty {
                            Text("None visible. This does not establish that the printer is unsupported. Ensure it is awake and paired in iOS Settings, then refresh.")
                        }
                        ForEach(probe.accessories, id: \.connectionID) { accessory in
                            VStack(alignment: .leading) {
                                Text(accessory.name).font(.headline)
                                Text("\(accessory.manufacturer) · \(accessory.modelNumber)")
                                if accessory.protocolStrings.isEmpty { Text("No protocols advertised yet.") }
                                ForEach(accessory.protocolStrings, id: \.self) { name in
                                    if Probe.protocols.contains(name) {
                                        Button("Passive connection test") { probe.start(accessory, protocolName: name) }
                                            .buttonStyle(.bordered)
                                            .accessibilityIdentifier("passive-" + name)
                                            .disabled(probe.active)
                                        Text(name).font(.caption)
                                        if accessory.modelNumber == "HPISPSLE" && name == "com.hp.protocol.lifestyle" {
                                            Button("Read firmware once") { probe.start(accessory, protocolName: name, readIdentity: true) }
                                                .buttonStyle(.borderedProminent)
                                                .accessibilityIdentifier("read-firmware")
                                                .disabled(probe.active)
                                        }
                                    } else { Text("Not tested: \(name)") }
                                }
                            }
                        }
                    }
                    Section("Local report") {
                        ShareLink("Share diagnostic report", item: probe.report)
                        Text("Review before sharing: names and unsolicited accessory data may be private.").font(.caption)
                        Text(probe.report).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                    }
                }
                .navigationTitle("Select Accessory Probe")
            }
            .onChange(of: phase) { value in
                if value != .active { probe.stop("App leaving foreground") }
            }
        }
    }
}
