import Foundation

/// Snapshot copied to the UI. A simulation never receives a native transport.
struct SimulationSnapshot: Sendable {
    var state: String = "review"
    var detail: String = "Review the image and settings, then confirm the simulated job."
    var acknowledgedBytes = 0
    var totalBytes = 0
    var printStarts = 0
    var requests = 0
    var running = false
    var confirmed = false
    var duplicateBlocked = false
    var recoveryAttempted = false
    let realPrinterBytes = 0
}
enum SimulationScenario: String, CaseIterable, Sendable {
    case success = "Successful job"
    case lostFinalReply = "Lose final reply"
    case interruptUpload = "Interrupt upload"
}

/// Fixed simulated destination. There is no backend selector, native adapter or
/// closure through which the UI can redirect these writes to ExternalAccessory.
actor SimulatedSubmission {
    let id: UUID
    private let jpeg: Data
    private let journalURL: URL
    private let device: String
    private var peer: SimulatedPrinter
    private var journal: JobJournal?
    private var coordinator: SubmissionCoordinator?
    private var now: TimeInterval = 0
    private var result = SimulationSnapshot()
    private var scenario: SimulationScenario = .success
    private var interrupted = false

    init(id: UUID, jpeg: Data, journalURL: URL) {
        self.id = id; self.jpeg = jpeg; self.journalURL = journalURL
        // Every review owns a distinct virtual printer, never a real accessory ID.
        device = id.uuidString.replacingOccurrences(of:"-",with:"").lowercased()
        peer = SimulatedPrinter(deviceID:device)
        result.totalBytes = jpeg.count
    }
    func snapshot() -> SimulationSnapshot { result }
    func confirm(scenario: SimulationScenario) -> SimulationSnapshot {
        guard !result.confirmed && result.state == "review" else {
            result.duplicateBlocked = true; return result
        }
        result.confirmed = true; self.scenario = scenario
        do {
            let image = try PreparedJobImage(jpeg:jpeg)
            try FileManager.default.createDirectory(at:journalURL.deletingLastPathComponent(),withIntermediateDirectories:true)
            let store = try JobJournal(url:journalURL); journal = store
            peer.dropFinalAck = scenario == .lostFinalReply
            coordinator = try SubmissionCoordinator(image:image,id:id,expectedDeviceID:device,journal:store,now:now,pollInterval:0.01)
            result.running = true; result.state = "preflight"; result.detail = "Checking the simulated printer. Real printing is disabled."
        } catch { result.state = "blocked"; result.detail = "Simulation could not start: \(error)" }
        return result
    }
    func advance(steps: Int = 128) -> SimulationSnapshot {
        guard result.running, let coordinator else { return result }
        for _ in 0..<max(0,min(steps,1024)) {
            guard !coordinator.terminal else { break }
            now += 0.002
            coordinator.write(now:now) { peer.write($0,limit:127) }
            if scenario == .interruptUpload && !interrupted && peer.received > 0 {
                interrupted = true; coordinator.disconnected(); break
            }
            peer.deliver(to:coordinator,now:now,limit:257)
            coordinator.tick(now:now)
        }
        refresh()
        return result
    }
    func cancel() -> SimulationSnapshot {
        if let coordinator, !coordinator.terminal { coordinator.cancel(); refresh() }
        else if !result.confirmed { result.state = "cancelled"; result.detail = "Closed before confirmation; no job created." }
        return result
    }
    func checkDuplicate() -> SimulationSnapshot {
        guard result.confirmed, !result.running, let journal else { return result }
        do {
            _ = try SubmissionCoordinator(image:PreparedJobImage(jpeg:jpeg),id:id,expectedDeviceID:device,journal:journal,now:now)
            result.detail = "No durable claim exists for this job; this review still cannot be confirmed again."
        } catch JobJournal.Failure.blocked {
            result.duplicateBlocked = true
            result.detail = "The saved job ID is blocked. No second simulated PrintStart was sent."
        } catch {
            result.detail = "Could not verify the saved claim: \(error). No second simulated job was sent."
        }
        return result
    }
    func recover() -> SimulationSnapshot {
        guard result.confirmed, !result.running, !result.recoveryAttempted, let journal else { return result }
        result.recoveryAttempted = true
        do {
            peer.input = []; peer.output = []
            coordinator = try SubmissionCoordinator(recover:id,journal:journal,now:now,timeout:3,pollInterval:0.01)
            result.running = true; result.state = "recovering"
            result.detail = "Read-only simulated recovery; image bytes cannot be resent."
        } catch { result.detail = "Saved evidence is insufficient for recovery: \(error)" }
        return result
    }
    private func refresh() {
        guard let coordinator else { return }
        result.state = coordinator.state.rawValue; result.running = !coordinator.terminal
        result.printStarts = peer.startCount; result.requests = peer.requests.count
        if let record = try? journal?.record(id) { result.acknowledgedBytes = record.acknowledgedBytes }
        switch coordinator.state {
        case .completed: result.detail = "Simulation completed. One virtual page processed; no real paper used."
        case .uncertain: result.detail = "Simulated outcome uncertain. The saved job blocks another submission. \(coordinator.error ?? "")"
        case .notSubmitted: result.detail = "Simulation stopped before submission. \(coordinator.error ?? "")"
        case .preflight: result.detail = "Checking the simulated printer."
        case .uploading: result.detail = "Transferring the frozen JPEG to memory only."
        case .observing: result.detail = "Checking the simulated job state and counters."
        }
    }
}
