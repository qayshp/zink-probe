import Foundation
import Combine

/// Narrow read-only interface for the view owner and offline lifecycle tests.
/// It deliberately has no submit, recovery, clock or settings operation.
protocol BLEPreflightAdapter: AnyObject {
    var active: Bool { get }
    var transportSummary: String { get }
    func preflight(peripheralID: UUID, expectedDeviceID: String?, expectedFirmware: String,
                   update: @escaping (AccessoryStreamPump) -> Void) throws
    func stop(_ reason: String)
}

extension BLEPreflightAdapter {
    var transportSummary: String { "" }
}

extension NativeBLEAdapter: BLEPreflightAdapter {}

/// Main-run-loop UI owner. Construction and selection do not start Bluetooth.
/// A generation token prevents a dismissed/replaced operation's callbacks from
/// changing the current result. Reports omit routing and protocol identities.
final class BLEPreflightController: ObservableObject {
    @Published private(set) var active = false
    @Published private(set) var status = "Ready for an explicitly selected BLE adapter preflight."
    @Published private(set) var report: String
    @Published private(set) var lastResult = ""
    private let adapter: BLEPreflightAdapter
    private var generation = UUID()
    private var opened = 0

    init(context: String, adapter: BLEPreflightAdapter = NativeBLEAdapter()) {
        self.adapter = adapter
        report = "Native BLE adapter read-only preflight · \(context). No automatic connection, printing or settings writes.\n"
    }

    func run(peripheralID: UUID, firmware: String) {
        precondition(Thread.isMainThread)
        guard !active, !adapter.active else { return }
        guard !firmware.isEmpty, firmware.utf8.count <= 128,
              firmware.utf8.allSatisfy({ (32...126).contains($0) }) else {
            status = "A successful BLE identity check is required before preflight."
            return
        }
        let attempt = UUID(); generation = attempt
        active = true; opened = 0; lastResult = ""
        status = "Opening the selected Select with the native BLE adapter…"
        log("Explicit native BLE preflight requested; expected firmware \(firmware). No print permit, image, clock or persistent-setting write.")
        do {
            try adapter.preflight(peripheralID: peripheralID, expectedDeviceID: nil, expectedFirmware: firmware) { [weak self] pump in
                guard let self, self.active, self.generation == attempt else { return }
                if pump.streamsOpened != self.opened {
                    self.opened = pump.streamsOpened
                    self.log("BLE negotiation complete; virtual streams opened=\(self.opened). Identity-bearing frames omitted.")
                }
                if pump.terminal {
                    self.active = false; self.lastResult = pump.result
                    self.status = pump.succeeded ? "Read-only BLE adapter preflight passed." : "Read-only BLE adapter preflight did not pass."
                    self.log("\(pump.result) Virtual stream TX=\(pump.acceptedBytes), RX=\(pump.receivedBytes); opened=\(pump.streamsOpened). These counts include internal framing, not raw GATT traffic. No printing or settings change.")
                    if !self.adapter.transportSummary.isEmpty { self.log(self.adapter.transportSummary) }
                    if pump.result.contains("Printer not idle/empty/error-free: flags=0x00000001") {
                        self.log("The printer reported its time-invalid flag during status checks. This action leaves the clock unchanged; a readiness refusal is separate from a BLE connection failure.")
                    }
                } else if pump.streamsOpened == 2 {
                    self.status = "Reading identity, capabilities, readiness, queue and counters…"
                }
            }
        } catch {
            guard generation == attempt, active else { return }
            generation = UUID(); active = false
            if adapter.active { adapter.stop("BLE preflight start refused") }
            status = "The native BLE preflight could not start."
            // Unknown framework errors can include device identifiers. The
            // fixed result is sufficient here; protocol errors use pump.result.
            lastResult = "Preflight start was refused; no retry, printing or settings write."
            log(lastResult)
        }
    }

    func stop(_ reason: String = "Stopped by user") {
        precondition(Thread.isMainThread)
        guard active || adapter.active else { return }
        generation = UUID(); active = false
        adapter.stop(reason)
        status = "Read-only BLE preflight stopped; no automatic retry."
        lastResult = reason
        log("\(reason). No image or print request was sent.")
    }

    private func log(_ message: String) {
        report += "\(ISO8601DateFormatter().string(from: Date())) \(message)\n"
        if report.count > 64000 { report = String(report.suffix(64000)) }
    }

    deinit { adapter.stop("BLE preflight owner released") }
}
