import SwiftUI
import UIKit

#if ZINK_EXPERIMENTAL_BLE_PRINT
struct BLEPilotView: View {
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var scanner = SelectBLEProbe(context: "BLE print pilot · identity check")
    @StateObject private var pilot = BLEPilotController()
    @State private var choosingPhoto = false
    @State private var photo: BLEPilotPhoto?
    @State private var review: BLEPilotReview?
    @State private var discard: BLEPilotJob?
    @State private var confirmingClockSync = false

    var body: some View {
        List {
            Section("One-sheet BLE pilot") {
                Text("Choose a photo and identify the printer. Check the printer to save a draft, then review the saved JPEG before authorizing one sheet.")
                Button(photo == nil ? "Prepare photo" : "Prepare a different photo") { choosingPhoto = true }
                    .disabled(pilot.active || scanner.active)
                if let photo {
                    Text("\(photo.settings.layout) · JPEG \(photo.settings.quality) · \(photo.image.jpeg.count.formatted()) bytes")
                        .font(.caption)
                }
            }
            Section("Printer") {
                Button("Scan for Select over BLE") {
                    pilot.clearPrinterCheck()
                    scanner.scan()
                }.disabled(scanner.active || pilot.active)
                ForEach(scanner.candidates) { candidate in
                    Button("Read identity for \(candidate.name)") {
                        pilot.clearPrinterCheck()
                        scanner.connect(candidate)
                    }.disabled(scanner.active || pilot.active)
                }
                Text(scanner.status).font(.caption)
                if scanner.active {
                    Button("Stop discovery") { scanner.stop() }
                }
                if let selection = scanner.checkedSelection {
                    Button(photo == nil ? "Check printer readiness" : "Check printer and save draft") {
                        pilot.check(selection, photo: photo)
                    }
                    .disabled(scanner.active || pilot.active)
                    if pilot.canSyncClock {
                        Button("Sync printer clock over BLE") { confirmingClockSync = true }
                            .disabled(scanner.active)
                            .accessibilityIdentifier("ble-pilot-clock")
                            .confirmationDialog("Sync the printer clock?", isPresented: $confirmingClockSync,
                                                titleVisibility: .visible) {
                                Button("Sync clock only") { pilot.syncClock() }
                                Button("Cancel", role: .cancel) {}
                            } message: {
                                Text("Send this iPhone’s current time and time zone to the selected printer. No photo is sent.")
                            }
                    }
                }
            }
            Section("Saved jobs") {
                if pilot.jobs.isEmpty {
                    Text("No active saved jobs.")
                }
                ForEach(pilot.jobs) { job in
                    jobRow(job)
                }
            }
            if let attempt = pilot.latestAttempt {
                Section("Last print attempt") {
                    Text(attempt.title).font(.headline)
                    Text(attempt.detail).font(.caption)
                    ShareLink("Share last print report", item: attempt.report)
                }
            }
            Section("Result") {
                if pilot.active {
                    ProgressView()
                    Button("Stop this check") { pilot.stop("Stopped by user.") }
                }
                Text(pilot.status).accessibilityIdentifier("ble-pilot-status")
                if !pilot.diagnostic.isEmpty {
                    Text(pilot.diagnostic).font(.caption).textSelection(.enabled)
                }
                if let report = pilot.report {
                    ShareLink("Share BLE pilot report", item: report)
                }
            }
        }
        .buttonStyle(.borderless)
        .navigationTitle("BLE print pilot")
        .task { pilot.reload() }
        .onChange(of: pilot.savedPhotoID) { id in
            if id == photo?.id { photo = nil }
        }
        .onChange(of: scenePhase) { phase in
            if phase == .background { stop("App entered the background.") }
            if phase == .active { pilot.reload() }
        }
        .onDisappear { stop("BLE pilot screen closed.") }
        .sheet(isPresented: $choosingPhoto) {
            NavigationStack {
                PhotoView(onBind: { prepared, layout, quality in
                    do {
                        photo = try BLEPilotPhoto(prepared: prepared, layout: layout, quality: quality)
                        choosingPhoto = false
                    } catch {
                        pilot.show("That JPEG could not be verified for submission.")
                        choosingPhoto = false
                    }
                })
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("Close") { choosingPhoto = false }
                    }
                }
            }
        }
        .sheet(item: $review) { item in
            BLEPilotConfirmation(review: item, pilot: pilot)
        }
        .alert("Discard this saved draft?", isPresented: Binding(
            get: { discard != nil }, set: { if !$0 { discard = nil } }
        ), presenting: discard) { job in
            Button("Discard draft", role: .destructive) { pilot.discard(job) }
            Button("Keep draft", role: .cancel) {}
        } message: { _ in
            Text("This removes the saved photo for this draft.")
        }
    }

    @ViewBuilder
    private func jobRow(_ job: BLEPilotJob) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Job \(job.id.uuidString.prefix(8)) · \(job.label)").font(.headline)
            Text("\(job.binding.settings.layout) · JPEG \(job.binding.settings.quality) · \(job.binding.sampling)").font(.caption)
            if job.canReview {
                Button("Review one-sheet print") { review = pilot.review(job) }
                    .disabled(!pilot.canReview(job) || scanner.active)
                    .accessibilityIdentifier("ble-pilot-review")
            } else if job.canRecover {
                Text("The previous attempt may still have printed. Check its outcome without resending the photo.").font(.caption)
                Button("Check job outcome read-only") {
                    if let selection = scanner.checkedSelection { pilot.recover(job, on: selection) }
                }
                .disabled(pilot.active || scanner.active || scanner.checkedSelection == nil)
            } else if !job.canDiscard {
                Text("The previous attempt was interrupted and cannot be matched to a printer job. It stays blocked to avoid a duplicate. Check the paper and do not resubmit.").font(.caption)
            }
            if job.canDiscard {
                Button("Discard saved draft", role: .destructive) { discard = job }
                    .disabled(pilot.active || scanner.active)
            }
        }
    }

    private func stop(_ reason: String) {
        confirmingClockSync = false
        scanner.stop(reason)
        pilot.stop(reason)
        pilot.clearPrinterCheck()
    }
}

private struct BLEPilotPhoto {
    let id = UUID()
    let image: PreparedJobImage
    let settings: JobBinding.Settings

    init(prepared: PreparedPhoto, layout: PhotoLayout, quality: Int) throws {
        image = try PreparedJobImage(jpeg: prepared.jpeg)
        settings = .init(layout: layout.rawValue, quality: quality)
    }
}

private struct BLEPilotJob: Identifiable {
    let binding: JobBinding
    let attempt: String?
    let record: JobJournal.Record?
    var id: UUID { binding.id }
    var canReview: Bool { attempt == nil && record == nil }
    var canDiscard: Bool { record == nil && (attempt == nil || attempt == "notSubmitted") }
    var canRecover: Bool {
        record?.printerJobID != nil && record?.baselinePages != nil
            && record?.baselineCalibrations != nil && record?.attributionBlocked != true
    }
    var label: String {
        if canReview { return "draft" }
        if canDiscard { return "did not submit" }
        return "outcome unresolved"
    }
}

private struct BLEPilotReview: Identifiable {
    let binding: JobBinding
    let preview: UIImage
    var id: UUID { binding.id }
}

private struct BLEPilotConfirmation: View {
    @Environment(\.dismiss) private var dismiss
    let review: BLEPilotReview
    @ObservedObject var pilot: BLEPilotController
    @State private var confirming = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    Image(uiImage: review.preview)
                        .resizable().scaledToFit().frame(maxHeight: 330)
                        .accessibilityLabel("Saved photo to print")
                    Text("One sheet on HP Sprocket Select").font(.headline)
                    Text("\(review.binding.settings.layout) · JPEG \(review.binding.settings.quality) · \(review.binding.sampling)\n768 × 1152 · \(review.binding.byteCount.formatted()) bytes\nFirmware \(review.binding.firmware)")
                        .font(.caption).multilineTextAlignment(.center)
                    Text("Keep this screen open while the printer receives the photo. If the connection ends, the printer may still finish. The app never retries automatically.")
                    Button("Continue to confirmation") { confirming = true }
                        .buttonStyle(.borderedProminent)
                        .disabled(!pilot.canSubmit(review))
                        .accessibilityIdentifier("ble-pilot-confirm")
                    if pilot.active {
                        if pilot.totalBytes > 0 {
                            ProgressView(value: Double(pilot.acknowledgedBytes), total: Double(pilot.totalBytes))
                            Text("\(pilot.acknowledgedBytes.formatted()) of \(pilot.totalBytes.formatted()) image bytes acknowledged")
                                .font(.caption)
                        } else {
                            ProgressView()
                        }
                        Button("Stop the connection") { pilot.stop("Stopped by user.") }
                    }
                    Text(pilot.status).accessibilityIdentifier("ble-pilot-print-status")
                    if !pilot.diagnostic.isEmpty {
                        Text(pilot.diagnostic).font(.caption).textSelection(.enabled)
                    }
                    if let report = pilot.report {
                        ShareLink("Share BLE pilot report", item: report)
                    }
                }.padding()
            }
            .navigationTitle("Review saved photo")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Close") { dismiss() }.disabled(pilot.active)
                }
            }
            .alert("Print one sheet over BLE?", isPresented: $confirming) {
                Button("Print one sheet") { pilot.submit(review) }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("This sends the saved JPEG to the checked Select and can use one sheet of paper.")
            }
        }
        .interactiveDismissDisabled(pilot.active)
    }
}

private final class BLEPilotController: ObservableObject {
    @Published private(set) var jobs: [BLEPilotJob] = []
    @Published private(set) var latestAttempt: JobJournal.PrintAttemptSummary?
    @Published private(set) var active = false
    @Published private(set) var status = "Ready for an explicit printer check."
    @Published private(set) var diagnostic = ""
    @Published private(set) var report: String?
    @Published private(set) var savedPhotoID: UUID?
    @Published private(set) var acknowledgedBytes = 0
    @Published private(set) var totalBytes = 0
    @Published private var checked: CheckedPrinter?
    @Published private var clockTarget: ClockTarget?
    private var submittedReviewIDs = Set<UUID>()
    private var startedAt = Date()
    private let adapter = NativeBLEAdapter()

    private struct CheckedPrinter {
        let route: UUID
        let printer: VerifiedPrinter
    }
    private struct ClockTarget {
        let selection: SelectBLEProbe.CheckedSelection
        let deviceID: String
    }

    func show(_ message: String) { status = message }
    func clearPrinterCheck() {
        checked = nil
        clockTarget = nil
    }
    var canSyncClock: Bool { !active && clockTarget != nil }

    func reload() {
        guard !active else { return }
        do {
            let store = try journal()
            jobs = try store.activeBindings().map { binding in
                try BLEPilotJob(binding: binding, attempt: store.attemptState(binding.id), record: store.record(binding.id))
            }
            latestAttempt = try? store.latestPrintAttempt()
        } catch {
            jobs = []
            latestAttempt = nil
            show("The private job store is unavailable. Unlock the device and reopen this screen.")
        }
    }

    func check(_ selection: SelectBLEProbe.CheckedSelection, photo: BLEPilotPhoto?) {
        guard !active else { return }
        clearPrinterCheck()
        begin("Checking printer readiness over BLE…")
        do {
            try adapter.preflight(peripheralID: selection.peripheralID, expectedFirmware: selection.firmware) { [weak self] pump in
                guard let self, pump.terminal else { return }
                self.active = false
                self.makeReport(pump, operation: "Read-only preflight")
                guard let printer = pump.verified else {
                    if let deviceID = pump.clockSyncDeviceID {
                        self.clockTarget = ClockTarget(selection: selection, deviceID: deviceID)
                    }
                    self.show(self.checkFailure(pump))
                    return
                }
                self.checked = CheckedPrinter(route: selection.peripheralID, printer: printer)
                guard let photo else {
                    self.show("The Select passed its readiness checks. You can review drafts bound to this printer.")
                    return
                }
                do {
                    _ = try self.journal().bind(id: photo.id, image: photo.image, settings: photo.settings, printer: printer,
                                                now: ProcessInfo.processInfo.systemUptime)
                    self.savedPhotoID = photo.id
                    self.show("Draft saved. Review the saved JPEG to authorize printing.")
                    self.reload()
                } catch {
                    self.show("The Select is ready, but the draft could not be saved. Check the saved jobs for an existing draft or unresolved attempt.")
                }
            }
        } catch {
            failStart("The BLE printer check could not start.")
        }
    }

    func syncClock() {
        guard canSyncClock, let target = clockTarget else { return }
        clearPrinterCheck()
        begin("Checking the printer before clock sync…")
        do {
            try adapter.syncClock(peripheralID: target.selection.peripheralID, expectedDeviceID: target.deviceID,
                                  expectedFirmware: target.selection.firmware) { [weak self] outcome in
                guard let self else { return }
                self.active = false
                self.diagnostic = self.adapter.transportSummary
                let formatter = ISO8601DateFormatter()
                self.report = [
                    "Select BLE pilot · Clock sync",
                    "Started \(formatter.string(from: self.startedAt)); ended \(formatter.string(from: Date()))",
                    outcome.summary,
                    self.diagnostic
                ].joined(separator: "\n")
                self.show(outcome.summary + " Run the printer check again before printing.")
            }
        } catch {
            failStart("Clock sync could not start. Run the printer check again.")
        }
    }

    func canReview(_ job: BLEPilotJob) -> Bool {
        job.canReview && !active && !submittedReviewIDs.contains(job.id) && checkedRoute(for: job.binding) != nil
    }

    func review(_ job: BLEPilotJob) -> BLEPilotReview? {
        guard canReview(job) else { return nil }
        do {
            let store = try journal()
            guard try store.binding(job.id) == job.binding, try store.attemptState(job.id) == nil,
                  let preview = UIImage(data: try store.boundImage(job.id).jpeg) else { throw JobJournal.Failure.blocked }
            return BLEPilotReview(binding: job.binding, preview: preview)
        } catch {
            show("The saved JPEG could not be verified. Printing is unavailable for this draft.")
            reload()
            return nil
        }
    }

    func canSubmit(_ review: BLEPilotReview) -> Bool {
        BLESubmissionAvailability.isEnabled && !active && !submittedReviewIDs.contains(review.id)
            && checkedRoute(for: review.binding) != nil
    }

    func submit(_ review: BLEPilotReview) {
        guard canSubmit(review), let route = checkedRoute(for: review.binding) else { return }
        submittedReviewIDs.insert(review.id)
        begin("Checking the bound printer before sending the photo…")
        do {
            try adapter.submitOnce(peripheralID: route, reviewed: review.binding, journal: try journal(),
                                   update: jobUpdate(operation: .submission, binding: review.binding))
        } catch {
            failStart("The one-sheet attempt could not start. Check the saved job state before taking any further action.")
        }
    }

    func recover(_ job: BLEPilotJob, on selection: SelectBLEProbe.CheckedSelection) {
        guard !active, job.canRecover, selection.firmware == job.binding.firmware else {
            show("Select the printer and firmware associated with this job before checking its outcome.")
            return
        }
        begin("Checking the previous attempt over BLE without sending the photo…")
        do {
            try adapter.recover(peripheralID: selection.peripheralID, id: job.id, journal: try journal(),
                                update: jobUpdate(operation: .recovery, binding: job.binding))
        } catch {
            failStart("Read-only recovery could not start. The job stays blocked to avoid a duplicate.")
        }
    }

    func stop(_ reason: String) {
        guard active else { return }
        adapter.stop(reason)
    }

    func discard(_ job: BLEPilotJob) {
        guard !active, job.canDiscard else { return }
        do {
            try journal().discardDraft(job.id)
            reload()
            show("Saved draft discarded.")
        } catch {
            show("The draft was not discarded. A possible submitted job cannot be removed.")
            reload()
        }
    }

    private func checkedRoute(for binding: JobBinding) -> UUID? {
        guard let checked, checked.printer.deviceID == binding.device,
              checked.printer.firmware == binding.firmware else { return nil }
        return checked.route
    }

    private func begin(_ message: String) {
        active = true
        startedAt = Date()
        acknowledgedBytes = 0
        totalBytes = 0
        diagnostic = ""
        report = nil
        show(message)
    }

    private func failStart(_ message: String) {
        active = false
        reload()
        show(message)
    }

    private func jobUpdate(operation: JobJournal.PrintAttemptDiagnostics.Operation,
                           binding: JobBinding) -> (AccessoryStreamPump) -> Void {
        { [weak self] pump in
            guard let self else { return }
            self.acknowledgedBytes = pump.acknowledgedImageBytes
            self.totalBytes = pump.totalImageBytes
            if !pump.terminal {
                if pump.jobState == "uploading" { self.show("Sending the saved photo over BLE…") }
                if pump.jobState == "observing" { self.show("Checking the printer’s job status…") }
                return
            }
            self.finishJob(pump, operation: operation, binding: binding)
        }
    }

    private func finishJob(_ pump: AccessoryStreamPump, operation: JobJournal.PrintAttemptDiagnostics.Operation,
                           binding: JobBinding) {
        let failureStage: JobJournal.PrintAttemptDiagnostics.FailureStage?
        switch adapter.failureStage {
        case .connection: failureStage = .connection
        case .setup: failureStage = .setup
        case .exchange: failureStage = .exchange
        case nil: failureStage = nil
        }
        let diagnostics = JobJournal.PrintAttemptDiagnostics(
            operation: operation, startedAt: startedAt, endedAt: Date(),
            acknowledgedImageBytes: pump.acknowledgedImageBytes, totalImageBytes: pump.totalImageBytes,
            gatt: adapter.transportCounters, failureStage: failureStage
        )
        let saved: Bool
        let attempt: JobJournal.PrintAttemptSummary?
        if let store = try? journal() {
            saved = (try? store.savePrintAttemptDiagnostics(diagnostics, for: binding.id)) != nil
            attempt = try? store.printAttempt(binding.id)
        } else {
            saved = false
            attempt = nil
        }
        active = false
        reload()
        diagnostic = adapter.transportSummary
        if let attempt {
            show(attempt.title + ". " + attempt.detail)
            if saved {
                report = attempt.report
                return
            }
        } else {
            show("The saved outcome could not be verified. Check the paper before taking any further action.")
        }
        makeReport(pump, operation: operation.label)
        if !saved { report = report.map { $0 + "\nThis session’s diagnostic details could not be saved." } }
    }

    private func checkFailure(_ pump: AccessoryStreamPump) -> String {
        if case let .printerStatus(flags, _, _, _, _, _)? = pump.readinessRefusal,
           flags & 1 != 0 {
            if pump.clockSyncDeviceID != nil {
                return "Printer connected. Clock sync needed. Choose Sync printer clock over BLE, then check readiness again."
            }
            return "Printer connected. Resolve the other readiness issues before syncing the clock, then run the printer check again."
        }
        if adapter.failureStage == .connection {
            return "BLE connection unavailable. Check that the Select is on, awake, and nearby, then retry manually."
        }
        return pump.result
    }

    private func makeReport(_ pump: AccessoryStreamPump, operation: String) {
        let formatter = ISO8601DateFormatter()
        diagnostic = adapter.transportSummary
        let state = pump.jobState ?? (pump.succeeded ? "passed" : "stopped")
        var lines = [
            "Select BLE pilot · \(operation)",
            "Started \(formatter.string(from: startedAt)); ended \(formatter.string(from: Date()))",
            "Protocol state: \(state); checks passed: \(pump.succeeded)",
            "Image bytes acknowledged by the printer in this session: \(pump.acknowledgedImageBytes) / \(pump.totalImageBytes)",
            diagnostic,
        ]
        if let failureStage = adapter.failureStage {
            lines.append("BLE failure stage: \(failureStage)")
        }
        if pump.jobState == "completed" {
            lines.append("Completion inferred from protocol status and counters. Physical ejection was not observed by the app.")
        }
        report = lines.joined(separator: "\n")
    }

    private func journal() throws -> JobJournal {
        let files = FileManager.default
        var directory = try files.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil,
                                      create: true).appendingPathComponent("SelectBLEPilotJobs", isDirectory: true)
        let protection: [FileAttributeKey: Any] = [.protectionKey: FileProtectionType.complete]
        try files.createDirectory(at: directory, withIntermediateDirectories: true, attributes: protection)
        try files.setAttributes(protection, ofItemAtPath: directory.path)
        var resources = URLResourceValues()
        resources.isExcludedFromBackup = true
        try directory.setResourceValues(resources)
        let url = directory.appendingPathComponent("jobs.sqlite")
        let store = try JobJournal(url: url)
        try files.setAttributes(protection, ofItemAtPath: url.path)
        return store
    }
}
#endif
