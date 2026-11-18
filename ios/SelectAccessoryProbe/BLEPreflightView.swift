import SwiftUI

/// Discovery/identity and the new native adapter are separate explicit steps.
/// The diagnostic owner has already closed its connection before it publishes
/// checkedSelection; the preflight never automatically follows a scan/read.
struct BLEPreflightView: View {
    @StateObject private var scanner: SelectBLEProbe
    @StateObject private var preflight: BLEPreflightController
    @Environment(\.scenePhase) private var scenePhase

    init(context: String) {
        _scanner = StateObject(wrappedValue: SelectBLEProbe(context: "\(context) · preflight identity check"))
        _preflight = StateObject(wrappedValue: BLEPreflightController(context: context))
    }

    var body: some View {
        List {
            Section("Read-only native BLE preflight") {
                Text("Checks the new BLE adapter used by the durable print coordinator. BLE printing remains disabled; this screen sends no image, allocates no print job and changes no printer settings.")
                Text("First find your Select and read its identity. After that connection closes, explicitly run the adapter preflight. It checks firmware, model, identity, capabilities, pause/status, queue and counters, stopping if a readiness check fails.").font(.caption)
            }
            Section("1. Find and identify the Select") {
                Button("Scan for Select over BLE") { scanner.scan() }
                    .disabled(scanner.active || preflight.active)
                    .accessibilityIdentifier("ble-preflight-scan")
                Text(scanner.checkedSelection != nil && !scanner.active
                     ? "Identity check passed. Run the separate native-adapter check below."
                     : scanner.status)
                    .accessibilityIdentifier("ble-preflight-discovery-status")
                ForEach(scanner.candidates) { item in
                    VStack(alignment: .leading) {
                        Text(item.name).font(.headline)
                        if let rssi = item.rssi { Text("Signal: \(rssi) dBm").font(.caption) }
                        Button("Read Select identity over BLE") { scanner.connect(item) }
                            .disabled(scanner.active || preflight.active)
                            .accessibilityIdentifier("ble-preflight-identify")
                    }
                }
                if scanner.active {
                    ProgressView()
                    Button("Stop discovery or identity check") { scanner.stop() }
                        .accessibilityIdentifier("ble-preflight-stop-discovery")
                }
            }
            Section("2. Check the native adapter") {
                if let selection = scanner.checkedSelection {
                    LabeledContent("Verified firmware", value: selection.firmware)
                    Button("Run BLE adapter preflight") {
                        preflight.run(peripheralID: selection.peripheralID, firmware: selection.firmware)
                    }
                    .disabled(scanner.active || preflight.active)
                    .accessibilityIdentifier("ble-adapter-preflight-run")
                } else {
                    Text("A successful identity check above is required. Selecting a device does not start preflight.").font(.caption)
                }
                Text(preflight.status).accessibilityIdentifier("ble-adapter-preflight-status")
                if preflight.active {
                    ProgressView()
                    Button("Stop BLE adapter preflight") { preflight.stop() }
                        .accessibilityIdentifier("ble-adapter-preflight-stop")
                }
                if !preflight.lastResult.isEmpty {
                    Text(preflight.lastResult).font(.caption)
                        .accessibilityIdentifier("ble-adapter-preflight-result")
                }
                Text("A clock-invalid, paused, low-battery or busy result can stop readiness checks even when BLE communication works. This screen does not clear flags or set the clock.").font(.caption)
            }
            Section("Adapter report") {
                ShareLink("Share BLE preflight report", item: preflight.report)
                Text("Reports omit device identifiers and raw identity frames. TX/RX counts here describe the coordinator's internal virtual streams, not a raw Bluetooth capture.").font(.caption)
                Text(preflight.report).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
            }
            Section("Identity-check report") {
                ShareLink("Share identity-check report", item: scanner.report)
                Text(scanner.report).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
            }
        }
        .buttonStyle(.borderless)
        .navigationTitle("BLE adapter preflight")
        .onDisappear { stop("BLE adapter preflight screen closed") }
        .onChange(of: scenePhase) { phase in
            if phase == .background { stop("BLE adapter preflight entered the background") }
        }
        .onReceive(NotificationCenter.default.publisher(for: .NSExtensionHostDidEnterBackground)) { _ in
            stop("Share host entered the background")
        }
    }

    private func stop(_ reason: String) {
        scanner.stop(reason)
        preflight.stop(reason)
    }
}
