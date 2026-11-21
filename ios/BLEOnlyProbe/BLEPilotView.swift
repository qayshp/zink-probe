import SwiftUI
import UIKit

#if ZINK_EXPERIMENTAL_BLE_PRINT
struct BLEPilotView: View {
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var scanner = SelectBLEProbe(context: "BLE print pilot · identity check")
    @StateObject private var pilot: BLEPilotController
    @State private var choosingPhoto = false
    @State private var draftSaveFailed = false
    @State private var confirmingRemovePhoto = false
    @State private var chosenRoute: UUID?
    @State private var printerAction: PrinterAction = .check
    @State private var review: BLEPilotReview?
    @State private var discard: BLEPilotJob?
    @State private var confirmingClockSync = false
    @State private var idleTimerWasDisabled: Bool?
    @State private var didScan = false
    private let fixturePhoto: Data?
    private let fixtureSelection: SelectBLEProbe.CheckedSelection?

    private enum PrinterAction {
        case check, retry(BLEPilotJob), recover(BLEPilotJob)
    }

    init() {
        _pilot = StateObject(wrappedValue: BLEPilotController(adapter: NativeBLEAdapter()))
        fixturePhoto = nil
        fixtureSelection = nil
    }

    #if DEBUG && targetEnvironment(simulator)
    init(adapter: any BLEPilotAdapter, fixturePhoto: Data,
         selection: SelectBLEProbe.CheckedSelection, storageRoot: URL) {
        _pilot = StateObject(wrappedValue: BLEPilotController(adapter: adapter, storageRoot: storageRoot))
        self.fixturePhoto = fixturePhoto
        fixtureSelection = selection
    }
    #endif

    var body: some View {
        List {
            photoSection
            printerSection
            if !pilot.jobs.isEmpty {
                Section("Saved jobs") {
                    ForEach(pilot.jobs) { job in
                        jobRow(job)
                    }
                }
            }
            if let attempt = pilot.latestAttempt {
                Section("Last print attempt") {
                    Text(attempt.title).font(.headline)
                    Text(attempt.detail).font(.caption)
                    ShareLink("Share last print report", item: attempt.report)
                }
            }
            if let report = pilot.report {
                Section {
                    ShareLink("Share BLE pilot report", item: report)
                }
            }
        }
        .buttonStyle(.borderless)
        .navigationTitle("BLE print pilot")
        .task { pilot.reload() }
        .onChange(of: scanner.checkedSelection) { selection in
            if let selection, selection.peripheralID == chosenRoute { perform(printerAction, on: selection) }
        }
        .onChange(of: pilot.keepScreenAwake) { setKeepAwake($0) }
        .onChange(of: scenePhase) { phase in
            if phase == .background { stop("App entered the background.") }
            if phase == .active { pilot.reload() }
        }
        .onDisappear { stop("BLE pilot screen closed.") }
        .sheet(isPresented: $choosingPhoto) {
            NavigationStack {
                PhotoView(initialData: fixturePhoto, draftActionTitle: "Save photo for printing",
                          keepsDraftActionVisible: true, onBind: { prepared, layout, quality in
                    if pilot.saveDraft(prepared: prepared, layout: layout, quality: quality) {
                        printerAction = .check
                        choosingPhoto = false
                    } else {
                        draftSaveFailed = true
                    }
                })
                .alert("Couldn’t save the photo", isPresented: $draftSaveFailed) {
                    Button("OK", role: .cancel) {}
                } message: {
                    Text("Check that the iPhone is unlocked and has storage available.")
                }
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
        .confirmationDialog("Sync the printer clock?", isPresented: $confirmingClockSync, titleVisibility: .visible) {
            Button("Sync clock only") { pilot.syncClock() }
                .accessibilityIdentifier("ble-pilot-sync-confirm")
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Send this iPhone’s current time and time zone to the selected printer.")
        }
        .alert(discardingEarlierDraft ? "Discard the earlier draft?" : "Discard this saved draft?", isPresented: Binding(
            get: { discard != nil }, set: { if !$0 { discard = nil } }
        ), presenting: discard) { job in
            Button("Discard draft", role: .destructive) { pilot.discard(job) }
            Button("Keep draft", role: .cancel) {}
        } message: { _ in
            Text(discardingEarlierDraft ? "Your new photo will stay saved on this iPhone."
                 : "This removes the saved photo for this draft.")
        }
    }

    private var discardingEarlierDraft: Bool {
        guard let discard else { return false }
        return discard.id == pilot.earlierDraft?.id
    }

    private var photoSection: some View {
        Section("Photo") {
            if let preview = pilot.preview {
                Image(uiImage: preview.image)
                    .resizable()
                    .scaledToFit()
                    .frame(maxHeight: 208)
                    .frame(maxWidth: .infinity)
                    .accessibilityLabel("Prepared photo preview")
                    .accessibilityIdentifier("ble-pilot-draft-preview")
                Text(preview.settings.layout + " · JPEG " + preview.settings.quality.formatted()).font(.caption)
            }
            Button(pilot.preview == nil ? "Choose photo" : "Choose a different photo") { choosingPhoto = true }
                .disabled(isBusy)
                .accessibilityIdentifier("ble-pilot-photo")
            if pilot.hasPreparedDraft {
                Button("Remove prepared photo", role: .destructive) { confirmingRemovePhoto = true }
                    .disabled(isBusy)
                    .confirmationDialog("Remove the prepared photo?", isPresented: $confirmingRemovePhoto,
                                        titleVisibility: .visible) {
                        Button("Remove prepared photo", role: .destructive) { pilot.discardPreparedDraft() }
                        Button("Cancel", role: .cancel) {}
                    }
            }
        }
    }

    private var printerSection: some View {
        Section("Printer") {
            Text(printerStatus).accessibilityIdentifier("ble-pilot-status")
            if isBusy {
                ProgressView()
                Button(scanner.active ? "Stop looking" : "Stop this check") {
                    chosenRoute = nil
                    if scanner.active { scanner.stop() } else { pilot.stop("Stopped by user.") }
                }
            } else {
                if pilot.canSyncClock {
                    Button("Sync printer clock") { confirmingClockSync = true }
                        .accessibilityIdentifier("ble-pilot-clock")
                } else if let job = pilot.earlierDraft {
                    Button("Discard earlier draft…", role: .destructive) { discard = job }
                        .accessibilityIdentifier("ble-pilot-discard-earlier")
                } else if let job = pilot.reviewJob, pilot.canReview(job) {
                    Button("Review one-sheet print") { review = pilot.review(job) }
                        .accessibilityIdentifier("ble-pilot-review")
                }
                if let selection = currentSelection {
                    Button("Check printer again") { perform(printerAction, on: selection) }
                        .accessibilityIdentifier("ble-pilot-recheck")
                }
                Button(currentSelection != nil ? "Find another Select" : didScan ? "Scan again" : "Find a Select") {
                    scan(for: .check)
                }
                    .accessibilityIdentifier("ble-pilot-scan")
                ForEach(candidates) { candidate in
                    Button {
                        select(candidate)
                    } label: {
                        VStack(alignment: .leading) {
                            Text("Check \(candidate.name)")
                            if candidate.id == pilot.lastCheckedRoute {
                                Text("Last verified printer").font(.caption)
                            }
                        }
                    }
                    .accessibilityIdentifier("ble-pilot-select-printer")
                }
            }
        }
    }

    @ViewBuilder
    private func jobRow(_ job: BLEPilotJob) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(job.label).font(.headline)
            Text("Job \(job.id.uuidString.prefix(8)) · \(job.binding.settings.layout) · JPEG \(job.binding.settings.quality)")
                .font(.caption)
            if let evidence = job.lastConfirmedStep {
                Text(evidence).font(.caption)
            }
            if !pilot.hasPreparedDraft, job.id != pilot.reviewJob?.id, pilot.canReview(job) {
                Button("Review saved photo") { review = pilot.review(job) }.disabled(isBusy)
            } else if job.canPrepareRetry, job.id != pilot.earlierDraft?.id {
                Button("Prepare another attempt") { findOrPerform(.retry(job)) }
                    .disabled(isBusy)
                    .accessibilityIdentifier("ble-pilot-prepare-retry")
            } else if job.canRecover {
                Button("Check outcome without printing") { findOrPerform(.recover(job)) }
                    .disabled(isBusy)
                    .accessibilityIdentifier("ble-pilot-check-outcome")
            } else if !job.canDiscard {
                Text("Check whether the sheet came out. This attempt stays blocked because its outcome cannot be verified.")
                    .font(.caption)
            }
            if job.canDiscard, job.id != pilot.earlierDraft?.id {
                Button("Discard saved draft", role: .destructive) { discard = job }
                    .disabled(isBusy)
            }
        }
    }

    private var isBusy: Bool { scanner.active || pilot.active }

    private var candidates: [SelectBLEProbe.Candidate] {
        guard didScan, chosenRoute == nil else { return [] }
        if let fixtureSelection {
            return [.init(id: fixtureSelection.peripheralID, name: "Simulator Select", rssi: nil, alreadyConnected: false)]
        }
        let preferred = scanner.candidates.filter { $0.id == pilot.lastCheckedRoute }
        return preferred + scanner.candidates.filter { $0.id != pilot.lastCheckedRoute }
    }

    private var currentSelection: SelectBLEProbe.CheckedSelection? {
        guard let chosenRoute else { return nil }
        let selection = fixtureSelection ?? scanner.checkedSelection
        return selection?.peripheralID == chosenRoute ? selection : nil
    }

    private var printerStatus: String {
        if scanner.active { return chosenRoute == nil ? "Looking for a Select…" : "Checking printer identity…" }
        if !candidates.isEmpty {
            switch printerAction {
            case .check: return "Choose the Select you want to check."
            case .retry: return "Choose the same Select to prepare a fresh attempt."
            case .recover: return "Choose the same Select to check the previous outcome."
            }
        }
        if fixtureSelection == nil, didScan, currentSelection == nil { return scanner.status }
        return pilot.status
    }

    private func scan(for action: PrinterAction) {
        printerAction = action
        chosenRoute = nil
        didScan = true
        pilot.clearPrinterCheck()
        if fixtureSelection == nil { scanner.scan() }
    }

    private func select(_ candidate: SelectBLEProbe.Candidate) {
        chosenRoute = candidate.id
        pilot.clearPrinterCheck()
        if let fixtureSelection {
            perform(printerAction, on: fixtureSelection)
        } else {
            scanner.connect(candidate)
        }
    }

    private func findOrPerform(_ action: PrinterAction) {
        printerAction = action
        if let selection = currentSelection {
            perform(action, on: selection)
        } else {
            scan(for: action)
        }
    }

    private func perform(_ action: PrinterAction, on selection: SelectBLEProbe.CheckedSelection) {
        switch action {
        case .check:
            pilot.check(selection)
        case .retry(let job):
            if pilot.jobs.contains(where: { $0.id == job.id && $0.canPrepareRetry }) {
                pilot.check(selection, retrying: job)
            } else {
                printerAction = .check
                pilot.check(selection)
            }
        case .recover(let job):
            printerAction = .check
            pilot.recover(job, on: selection)
        }
    }

    private func setKeepAwake(_ enabled: Bool) {
        if enabled {
            guard idleTimerWasDisabled == nil else { return }
            idleTimerWasDisabled = UIApplication.shared.isIdleTimerDisabled
            UIApplication.shared.isIdleTimerDisabled = true
        } else if let idleTimerWasDisabled {
            UIApplication.shared.isIdleTimerDisabled = idleTimerWasDisabled
            self.idleTimerWasDisabled = nil
        }
    }

    private func stop(_ reason: String) {
        confirmingClockSync = false
        confirmingRemovePhoto = false
        chosenRoute = nil
        didScan = false
        scanner.stop(reason)
        pilot.stop(reason)
        pilot.clearPrinterCheck()
        setKeepAwake(false)
    }
}

private struct BLEPilotPreview {
    let image: UIImage
    let settings: JobBinding.Settings
}

private struct BLEPilotJob: Identifiable {
    let binding: JobBinding
    let attempt: String?
    let record: JobJournal.Record?
    var id: UUID { binding.id }
    var canReview: Bool { attempt == nil && record == nil }
    var canPrepareRetry: Bool { attempt == "notSubmitted" && record == nil }
    var canDiscard: Bool { canReview || canPrepareRetry }
    var canRecover: Bool {
        record?.printerJobID != nil && record?.baselinePages != nil
            && record?.baselineCalibrations != nil && record?.attributionBlocked != true
    }
    var label: String {
        if canReview { return "Ready for review" }
        if canPrepareRetry { return "Stopped before submission" }
        return "Print outcome uncertain"
    }
    var lastConfirmedStep: String? {
        guard !canReview, !canPrepareRetry else { return nil }
        if record?.seenPrinting == true { return "The printer reported it was printing." }
        if record?.uploadAcknowledged == true { return "The printer acknowledged the photo." }
        if record?.printerJobID != nil { return "The printer acknowledged the job start." }
        return "The printer did not confirm a job number."
    }
}

protocol BLEPilotAdapter: AnyObject {
    var failureStage: BLESubmissionDuplex.FailureStage? { get }
    var transportCounters: JobJournal.PrintAttemptDiagnostics.GATT? { get }
    var transportSummary: String { get }
    func preflight(peripheralID: UUID, expectedDeviceID: String?, expectedFirmware: String,
                   update: @escaping (AccessoryStreamPump) -> Void) throws
    func recover(peripheralID: UUID, id: UUID, journal: JobJournal,
                 update: @escaping (AccessoryStreamPump) -> Void) throws
    func submitOnce(peripheralID: UUID, reviewed: JobBinding, journal: JobJournal,
                    update: @escaping (AccessoryStreamPump) -> Void) throws
    func syncClock(peripheralID: UUID, expectedDeviceID: String, expectedFirmware: String,
                   update: @escaping (BLEClockSession.Outcome) -> Void) throws
    func stop(_ reason: String)
}

extension NativeBLEAdapter: BLEPilotAdapter {}

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
                    Text(review.binding.settings.layout).font(.subheadline)
                    if pilot.canSubmit(review) || pilot.active {
                        Text("Keep this screen open until the result appears.")
                    }
                    if pilot.canSubmit(review) {
                        Button("Print one sheet…") { confirming = true }
                            .buttonStyle(.borderedProminent)
                            .accessibilityIdentifier("ble-pilot-confirm")
                    }
                    if pilot.active {
                        if pilot.totalBytes > 0 && pilot.acknowledgedBytes < pilot.totalBytes {
                            ProgressView(value: Double(pilot.acknowledgedBytes), total: Double(pilot.totalBytes))
                        } else {
                            ProgressView()
                        }
                        Button("Stop the connection") { pilot.stop("Stopped by user.") }
                    }
                    Text(pilot.status).accessibilityIdentifier("ble-pilot-print-status")
                    if let attempt = pilot.latestAttempt, attempt.id == review.id {
                        ShareLink("Share last print report", item: attempt.report)
                    }
                    DisclosureGroup("Technical details") {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("JPEG \(review.binding.settings.quality) · \(review.binding.sampling)\n768 × 1152 · \(review.binding.byteCount.formatted()) bytes\nFirmware \(review.binding.firmware)")
                                .accessibilityIdentifier("ble-pilot-image-details")
                            if !pilot.diagnostic.isEmpty {
                                Text(pilot.diagnostic).textSelection(.enabled)
                            }
                            if let report = pilot.report {
                                ShareLink("Share session diagnostics", item: report)
                            }
                        }.font(.caption)
                    }
                    .accessibilityIdentifier("ble-pilot-technical-details")
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
                    .accessibilityIdentifier("ble-pilot-print")
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
    @Published private(set) var preview: BLEPilotPreview?
    @Published private(set) var reviewJob: BLEPilotJob?
    @Published private(set) var lastCheckedRoute: UUID?
    @Published private(set) var active = false
    @Published private(set) var status = "Find your printer when you’re ready to check it."
    @Published private(set) var diagnostic = ""
    @Published private(set) var report: String?
    @Published private(set) var acknowledgedBytes = 0
    @Published private(set) var totalBytes = 0
    @Published private(set) var keepScreenAwake = false
    @Published private var checked: CheckedPrinter?
    @Published private var clockTarget: ClockTarget?
    private var preparedDraft: BLEPilotDraft?
    private var focusedJobID: UUID?
    private var submittedReviewIDs = Set<UUID>()
    private var startedAt = Date()
    private let adapter: any BLEPilotAdapter
    private let storageRoot: URL?

    init(adapter: any BLEPilotAdapter, storageRoot: URL? = nil) {
        self.adapter = adapter
        self.storageRoot = storageRoot
    }

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
    var hasPreparedDraft: Bool { preparedDraft != nil }
    private var previousJobForPreparedDraft: BLEPilotJob? {
        guard hasPreparedDraft, let checked else { return nil }
        return jobs.first { $0.binding.device == checked.printer.deviceID }
    }
    var earlierDraft: BLEPilotJob? {
        guard let job = previousJobForPreparedDraft, job.canDiscard else { return nil }
        return job
    }

    func reload() {
        guard !active else { return }
        let store: JobJournal
        do {
            store = try journal()
            jobs = try store.activeBindings().map { binding in
                try BLEPilotJob(binding: binding, attempt: store.attemptState(binding.id), record: store.record(binding.id))
            }
            latestAttempt = try? store.latestPrintAttempt()
        } catch {
            jobs = []
            latestAttempt = nil
            reviewJob = nil
            show("The private job store is unavailable. Unlock the iPhone and reopen the pilot.")
            return
        }
        do {
            if lastCheckedRoute == nil, let url = try? directory().appendingPathComponent("last-verified-route"),
               let value = try? String(contentsOf: url, encoding: .utf8) {
                lastCheckedRoute = UUID(uuidString: value)
            }
            let drafts = try draftStore()
            preparedDraft = try drafts.load()
            if let preparedDraft, try store.binding(preparedDraft.id) != nil {
                // A previous bind may have committed just before the app closed.
                try? drafts.discard(id: preparedDraft.id)
                self.preparedDraft = nil
            }
            updatePreview(using: store)
        } catch {
            preparedDraft = nil
            updatePreview(using: store)
            show("The saved photo couldn’t be loaded. Unlock the iPhone and reopen the pilot, or choose the photo again.")
        }
    }

    func saveDraft(prepared: PreparedPhoto, layout: PhotoLayout, quality: Int) -> Bool {
        guard !active else { return false }
        do {
            let image = try PreparedJobImage(jpeg: prepared.jpeg)
            let draft = BLEPilotDraft(id: UUID(), image: image, settings: .init(layout: layout.rawValue, quality: quality))
            try draftStore().save(draft)
            preparedDraft = draft
            focusedJobID = nil
            updatePreview()
            show(earlierDraft == nil ? "Photo saved. Check your Select to review the print."
                 : "Your new photo is saved. Discard the earlier draft for this printer, then check again.")
            return true
        } catch {
            show("The photo couldn’t be saved. Check that the iPhone is unlocked and has storage available.")
            return false
        }
    }

    func discardPreparedDraft() {
        guard !active, let draft = preparedDraft else { return }
        do {
            try draftStore().discard(id: draft.id)
            reload()
            show("Prepared photo removed.")
        } catch {
            show("The prepared photo couldn’t be removed. Unlock the iPhone and try again.")
        }
    }

    func check(_ selection: SelectBLEProbe.CheckedSelection, retrying: BLEPilotJob? = nil) {
        guard !active else { return }
        clearPrinterCheck()
        begin("Checking printer…")
        do {
            try adapter.preflight(peripheralID: selection.peripheralID, expectedDeviceID: retrying?.binding.device,
                                  expectedFirmware: selection.firmware) { [weak self] pump in
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
                self.rememberVerifiedRoute(selection.peripheralID)
                do {
                    let store = try self.journal()
                    let now = ProcessInfo.processInfo.systemUptime
                    if let retrying {
                        let next = try store.prepareNewAttempt(from: retrying.id, newID: UUID(), printer: printer, now: now)
                        self.focusedJobID = next.id
                    } else if let draft = self.preparedDraft {
                        let bound = try store.bind(id: draft.id, image: draft.image, settings: draft.settings,
                                                   printer: printer, now: now)
                        self.focusedJobID = bound.id
                        try? self.draftStore().discard(id: draft.id)
                        self.preparedDraft = nil
                    }
                    self.reload()
                    if self.jobs.contains(where: { self.canReview($0) }) {
                        self.show("Printer ready. Review the saved photo to print one sheet.")
                    } else if self.jobs.contains(where: { $0.binding.device == printer.deviceID }) {
                        self.show("Printer ready. Check the saved job before starting another print.")
                    } else {
                        self.show("Printer ready. Choose a photo to prepare a print.")
                    }
                } catch JobJournal.Failure.blocked {
                    self.reload()
                    if self.earlierDraft != nil {
                        self.show("Your new photo is saved. Discard the earlier draft for this printer, then check again.")
                    } else if self.previousJobForPreparedDraft != nil {
                        self.show("Your new photo is saved. Check the previous print outcome before starting another.")
                    } else {
                        self.show("Printer ready. Check your saved jobs before proceeding.")
                    }
                } catch {
                    self.show("Printer ready. Review or resolve any existing saved job before preparing another print.")
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
        begin("Checking printer…")
        keepScreenAwake = true
        do {
            try adapter.submitOnce(peripheralID: route, reviewed: review.binding, journal: try journal(),
                                   update: jobUpdate(operation: .submission, binding: review.binding))
        } catch {
            if let store = try? journal() {
                do {
                    if try store.attemptState(review.id) == nil { submittedReviewIDs.remove(review.id) }
                } catch { /* Keep the review blocked until the journal can be read. */ }
            }
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
        keepScreenAwake = false
        guard active else { return }
        adapter.stop(reason)
    }

    func discard(_ job: BLEPilotJob) {
        guard !active, job.canDiscard else { return }
        let replacing = earlierDraft?.id == job.id
        do {
            try journal().discardDraft(job.id)
            reload()
            show(replacing ? "Earlier draft discarded. Check the printer again to review your new photo."
                 : "Saved draft discarded.")
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

    private func updatePreview(using store: JobJournal? = nil) {
        if let preparedDraft {
            preview = UIImage(data: preparedDraft.image.jpeg).map {
                BLEPilotPreview(image: $0, settings: preparedDraft.settings)
            }
            reviewJob = nil
            return
        }
        let available = jobs.filter(\.canReview)
        reviewJob = available.first(where: { $0.id == focusedJobID }) ?? (available.count == 1 ? available.first : nil)
        guard let store, let job = reviewJob, let savedImage = try? store.boundImage(job.id),
              let image = UIImage(data: savedImage.jpeg) else {
            preview = nil
            return
        }
        preview = BLEPilotPreview(image: image, settings: job.binding.settings)
    }

    private func rememberVerifiedRoute(_ route: UUID) {
        lastCheckedRoute = route
        if let file = try? directory().appendingPathComponent("last-verified-route") {
            try? Data(route.uuidString.utf8).write(to: file, options: [.atomic, .completeFileProtection])
        }
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
        keepScreenAwake = false
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
                if pump.jobState == "uploading" { self.show("Sending photo…") }
                if pump.jobState == "observing" {
                    self.show(operation == .submission ? "Waiting for printer…" : "Checking the previous print…")
                }
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
        keepScreenAwake = false
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
        if let refusal = pump.readinessRefusal {
            switch refusal {
            case .paused:
                return "Printing is paused. Resume the printer, then check again."
            case .batteryOrPower:
                return "The printer needs more power. Charge it and check again."
            case .queuedJobs:
                return "The printer has a job queued. Wait for it to finish, then check again."
            case .printerStatus(let flags, let state, let currentJob, let queue, let battery, let power):
                if pump.clockSyncDeviceID != nil {
                    return "The printer’s clock needs to be set. Sync the clock, then check the printer again."
                }
                if currentJob != 0 || queue != 1 || state != 1 {
                    return "The printer isn’t idle. Check its status or wait for its current job, then check again."
                }
                if battery < 30 || ![1, 2].contains(power) {
                    return "The printer needs more power. Charge it and check again."
                }
                if flags != 0 {
                    return "The printer reports an error. Check its status light and paper, then check again."
                }
            }
        }
        switch adapter.failureStage {
        case .connection:
            return "Couldn’t reach the printer. Check that Bluetooth is on and the Select is awake and nearby."
        case .setup, .exchange:
            return "The printer connection was interrupted. Check that the Select is nearby, then check again."
        case nil:
            return "The printer check didn’t pass. Select the intended printer and check again."
        }
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

    private func directory() throws -> URL {
        let files = FileManager.default
        var directory: URL
        if let storageRoot {
            directory = storageRoot
        } else {
            directory = try files.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil,
                                      create: true).appendingPathComponent("SelectBLEPilotJobs", isDirectory: true)
        }
        let protection: [FileAttributeKey: Any] = [.protectionKey: FileProtectionType.complete]
        try files.createDirectory(at: directory, withIntermediateDirectories: true, attributes: protection)
        try files.setAttributes(protection, ofItemAtPath: directory.path)
        var resources = URLResourceValues()
        resources.isExcludedFromBackup = true
        try directory.setResourceValues(resources)
        return directory
    }

    private func draftStore() throws -> BLEPilotDraftStore {
        try BLEPilotDraftStore(url: directory().appendingPathComponent("prepared-draft"))
    }

    private func journal() throws -> JobJournal {
        let url = try directory().appendingPathComponent("jobs.sqlite")
        let store = try JobJournal(url: url)
        try FileManager.default.setAttributes([.protectionKey: FileProtectionType.complete], ofItemAtPath: url.path)
        return store
    }
}
#endif
