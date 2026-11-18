import Foundation
import Combine

/// Narrow read-only interface for the view owner and offline lifecycle tests.
/// It deliberately has no submit, recovery, clock or settings operation.
protocol BLEPreflightAdapter: AnyObject {
    var active: Bool { get }
    var transportSummary: String { get }
    var failureStage: BLESubmissionDuplex.FailureStage? { get }
    func preflight(peripheralID: UUID, expectedDeviceID: String?, expectedFirmware: String,
                   update: @escaping (AccessoryStreamPump) -> Void) throws
    func stop(_ reason: String)
}

extension BLEPreflightAdapter {
    var transportSummary: String { "" }
    var failureStage: BLESubmissionDuplex.FailureStage? { nil }
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
                    let outcome = self.outcome(pump)
                    self.active = false; self.lastResult = outcome.detail
                    self.status = outcome.status
                    self.log("\(pump.result) Virtual stream TX=\(pump.acceptedBytes), RX=\(pump.receivedBytes); opened=\(pump.streamsOpened). These counts include internal framing, not raw GATT traffic. No printing or settings change.")
                    if !self.adapter.transportSummary.isEmpty { self.log(self.adapter.transportSummary) }
                    if !pump.succeeded { self.log("\(outcome.status) \(outcome.detail)") }
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

    /// Human guidance uses typed, validated observations. Raw bounded protocol
    /// diagnostics remain in the report; unknown framework error text stays out.
    private func outcome(_ pump: AccessoryStreamPump) -> (status: String, detail: String) {
        if pump.succeeded { return ("Read-only BLE adapter preflight passed.", pump.result) }
        if let refusal = pump.readinessRefusal {
            switch refusal {
            case let .printerStatus(flags, state, currentJob, queue, battery, power) where flags & 1 != 0:
                let otherBlockers = flags & ~1 != 0 || state != 1 || currentJob != 0 || queue != 1 || battery < 30 || ![1,2].contains(power)
                let status = otherBlockers
                    ? "Printer connected; clock sync and other checks need attention."
                    : "Printer connected; clock sync needed."
                let guidance = otherBlockers
                    ? "Other status, queue, or battery/power conditions also prevent readiness. Use the separate clock-sync action in Select Probe and check the printer status, then run this check again."
                    : "Use the separate clock-sync action in Select Probe, then run this check again."
                return (status, "The Select replied over BLE and reported that its clock needs syncing. \(guidance) This check left the clock unchanged. No automatic retry.")
            case .paused:
                return ("Printer connected; not ready.", "The Select replied over BLE and reported that it is paused. Check its status and resume it separately before running this check again. This check left the clock and settings unchanged. No automatic retry.")
            case .batteryOrPower:
                return ("Printer connected; not ready.", "The Select replied over BLE, but its battery or power state does not meet the readiness requirements. Check its power and charge level, then run this check again. This check left the clock and settings unchanged. No automatic retry.")
            case .queuedJobs:
                return ("Printer connected; not ready.", "The Select replied over BLE and reported jobs in its queue. Check the existing jobs before running this check again. This check left the clock and settings unchanged. No automatic retry.")
            case .printerStatus:
                return ("Printer connected; not ready.", "The Select replied over BLE and reported status flags or a busy printer/queue state. Check the printer status, then run this check again when it is ready. This check left the clock and settings unchanged. No automatic retry.")
            }
        }
        switch adapter.failureStage {
        case .connection:
            return ("BLE connection unavailable.", "A usable BLE connection to the selected printer could not be established. Check that the printer is on, awake and nearby, and that Bluetooth access is enabled. Then retry manually. No automatic retry or clock update.")
        case .setup:
            return ("BLE setup did not complete.", "The BLE adapter opened, but protocol setup did not complete. No printer readiness result is available. Retry manually after checking the connection. No automatic retry or clock update.")
        case .exchange:
            return ("BLE communication did not complete.", "The BLE exchange failed or was interrupted. Printer readiness was not confirmed. Retry manually after checking the connection. No automatic retry or clock update.")
        case nil:
            return ("BLE printer check did not complete.", "Printer readiness could not be verified. See the diagnostic report for details. No automatic retry or clock update.")
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
