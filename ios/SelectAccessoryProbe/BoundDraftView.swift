import SwiftUI

/// One extension-owned store. No per-session path or app-container fallback on
/// physical devices; the main app cannot own live jobs in this milestone.
actor LiveDraftStorage {
    struct Saved: Identifiable, Sendable { let binding: JobBinding; let state: String; var id: UUID { binding.id } }
    static func storeURL() throws -> URL {
        #if targetEnvironment(simulator)
        let name = "SelectLiveJobs-SIMULATOR-ONLY"
        #else
        guard Bundle.main.bundleURL.pathExtension == "appex" else { throw JobJournal.Failure.storage("Live jobs belong to the Share extension") }
        let name = "SelectLiveJobs"
        #endif
        var root = FileManager.default.urls(for:.applicationSupportDirectory,in:.userDomainMask)[0].appendingPathComponent(name)
        try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true,attributes:[.protectionKey:FileProtectionType.complete])
        try FileManager.default.setAttributes([.protectionKey:FileProtectionType.complete],ofItemAtPath:root.path)
        var values = URLResourceValues(); values.isExcludedFromBackup = true; try root.setResourceValues(values)
        return root.appendingPathComponent("jobs.sqlite")
    }
    private func journal() throws -> JobJournal {
        let url = try Self.storeURL(), store = try JobJournal(url:url)
        try FileManager.default.setAttributes([.protectionKey:FileProtectionType.complete],ofItemAtPath:url.path)
        return store
    }
    func save(id: UUID, jpeg: Data, settings: JobBinding.Settings, printer: VerifiedPrinter) throws -> JobBinding {
        try journal().bind(id:id,image:PreparedJobImage(jpeg:jpeg),settings:settings,printer:printer,now:ProcessInfo.processInfo.systemUptime)
    }
    func saved() throws -> [Saved] {
        let store = try journal()
        return try store.activeBindings().map { Saved(binding:$0,state:try store.record($0.id)?.state ?? store.attemptState($0.id) ?? "unsubmitted") }
    }
    func discard(_ id: UUID) throws { try journal().discardDraft(id) }
    func validate(_ id: UUID) throws -> JobBinding {
        let store = try journal(); _ = try store.boundImage(id)
        guard let binding = try store.binding(id) else { throw JobJournal.Failure.invalidRecord }; return binding
    }
    struct Review: Sendable { let binding: JobBinding; let jpeg: Data; let attempt: String? }
    func review(_ id: UUID) throws -> Review {
        let store = try journal(), image = try store.boundImage(id)
        guard let binding = try store.binding(id) else { throw JobJournal.Failure.invalidRecord }
        return Review(binding:binding,jpeg:image.jpeg,attempt:try store.attemptState(id))
    }
}

struct SharePhotoFlow: View {
    private enum Review: Identifiable {
        case simulation(PreparedPhotoReview), draft(PreparedPhotoReview)
        var id: UUID { switch self { case .simulation(let r), .draft(let r): return r.id } }
    }
    let initialData: Data
    @ObservedObject var connection: ShareConnectionProbe
    @State private var review: Review?
    var body: some View {
        PhotoView(initialData:initialData,onReview:{ photo,layout,quality in
            review = .simulation(PreparedPhotoReview(photo:photo,layout:layout,quality:quality))
        },onBind:{ photo,layout,quality in
            review = .draft(PreparedPhotoReview(photo:photo,layout:layout,quality:quality))
        })
        .sheet(item:$review) { item in
            switch item {
            case .simulation(let frozen): SimulationConfirmationView(review:frozen)
            case .draft(let frozen): BoundDraftView(review:frozen,connection:connection)
            }
        }
    }
}

struct BoundDraftView: View {
    let review: PreparedPhotoReview
    @ObservedObject var connection: ShareConnectionProbe
    @Environment(\.dismiss) private var dismiss
    @State private var message = "Run a full preflight for the selected printer before saving. Saving is not a print authorization."
    @State private var saved = false
    @State private var busy = false
    private let storage = LiveDraftStorage()
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment:.leading,spacing:16) {
                    Text("Saving a draft uses no paper").font(.headline)
                    Image(uiImage:UIImage(cgImage:review.preview)).resizable().scaledToFit().frame(maxHeight:180).frame(maxWidth:.infinity)
                    Text("One copy · \(review.layout) · JPEG \(review.quality)\n768 × 1152 · \(review.jpeg.count.formatted()) bytes\n\(JPEGDetails.sampling(review.jpeg))")
                    Text("The exact JPEG and settings will be saved privately on this iPhone and bound to the printer's verified identity.").font(.caption)
                    Button("Refresh connected accessories") { connection.refresh() }.disabled(connection.active || saved)
                    ForEach(connection.accessories,id:\.connectionID) { accessory in
                        Button("Check \(accessory.name) read-only") { connection.preflight(accessory) }.disabled(connection.active || saved)
                    }
                    #if targetEnvironment(simulator)
                    Button("Simulate full preflight (no accessory)") { connection.simulatePreflight() }.disabled(connection.active || saved)
                    #endif
                    if connection.active { ProgressView(); Button("Stop check") { connection.stop() } }
                    if let printer = connection.verifiedPrinter {
                        Text("Full preflight passed · \(printer.firmware)").accessibilityIdentifier("binding-preflight-passed")
                        Button("Save bound draft — no printing") {
                            busy = true
                            Task {
                                do {
                                    _ = try await storage.save(id:review.id,jpeg:review.jpeg,settings:.init(layout:review.layout,quality:review.quality),printer:printer)
                                    saved = true; message = "Bound draft saved. No print authorized or sent. Reopen Saved printer drafts to verify it."
                                } catch { message = "Draft not saved: \(error). A recent preflight and an available printer reservation are required." }
                                busy = false
                            }
                        }.buttonStyle(.borderedProminent).disabled(saved || busy || connection.active)
                            .accessibilityIdentifier("save-bound-draft")
                    }
                    Text(message).accessibilityIdentifier("bound-draft-result")
                    NavigationLink("Saved printer drafts") { SavedDraftsView(connection:connection) }
                    Text(connection.report).font(.system(.caption,design:.monospaced)).textSelection(.enabled)
                }.padding()
            }
            .navigationTitle("Bind a draft")
            .toolbar { ToolbarItem(placement:.cancellationAction) { Button("Close") { dismiss() } } }
        }
        .onDisappear { connection.stop("Draft review closed") }
    }
}

struct SavedDraftsView: View {
    private struct PrintReview: Identifiable { let id: UUID }
    @ObservedObject var connection: ShareConnectionProbe
    @State private var drafts: [LiveDraftStorage.Saved] = []
    @State private var message = ""
    @State private var discard: UUID?
    @State private var printReview: PrintReview?
    private let storage = LiveDraftStorage()
    var body: some View {
        List {
            Text("Saved privately by this extension. Printing requires a separate photo review and explicit one-copy confirmation. An unresolved job cannot be resent here.")
            Button("Refresh connected accessories") { connection.refresh() }.disabled(connection.active)
            if connection.active { ProgressView(); Button("Stop read-only check") { connection.stop() } }
            ForEach(drafts) { saved in
                VStack(alignment:.leading,spacing:8) {
                    Text("Job \(saved.id.uuidString.prefix(8)) · \(saved.state)").font(.headline)
                    Text("\(saved.binding.settings.layout) · JPEG \(saved.binding.settings.quality) · \(saved.binding.sampling) · \(saved.binding.byteCount.formatted()) bytes")
                    if saved.state == "unsubmitted" {
                        Button("Review one-photo print") { printReview = PrintReview(id:saved.id) }.disabled(connection.active)
                            .accessibilityIdentifier("review-one-print")
                    }
                    Button("Verify saved JPEG") {
                        Task {
                            do { _ = try await storage.validate(saved.id); message = "Saved JPEG integrity verified for job \(saved.id.uuidString.prefix(8)). No new job ID created." }
                            catch { message = "Saved draft integrity check failed: \(error)" }
                        }
                    }
                    ForEach(connection.accessories,id:\.connectionID) { accessory in
                        Button("Check bound printer read-only") { connection.preflight(accessory,expectedDeviceID:saved.binding.device) }.disabled(connection.active)
                        if !["unsubmitted","notSubmitted"].contains(saved.state) {
                            Button("Recover saved job read-only") { connection.recover(accessory,id:saved.id) }.disabled(connection.active)
                        }
                    }
                    if ["unsubmitted","notSubmitted"].contains(saved.state) { Button("Discard unsubmitted draft",role:.destructive) { discard = saved.id }.disabled(connection.active) }
                }
            }
            Button("Refresh saved drafts") { reload() }
            Text(message).accessibilityIdentifier("saved-draft-result")
            Text(connection.report).font(.system(.caption,design:.monospaced)).textSelection(.enabled)
        }
        .buttonStyle(.borderless)
        .navigationTitle("Saved printer drafts")
        .task { reload() }
        .onChange(of:connection.active) { if !$0 { reload() } }
        .sheet(item:$printReview) { item in PrintSavedJobSheet(id:item.id,connection:connection) }
        .confirmationDialog("Discard this unsubmitted draft?",isPresented:Binding(get:{ discard != nil },set:{ if !$0 { discard = nil } })) {
            Button("Discard draft",role:.destructive) {
                guard let id = discard else { return }; discard = nil
                Task { do { try await storage.discard(id); reload() } catch { message = "Discard refused: \(error)" } }
            }
        }
        .onDisappear { connection.stop("Saved drafts screen closed") }
    }
    private func reload() {
        Task {
            do { drafts = try await storage.saved(); message = drafts.isEmpty ? "No active saved drafts." : "\(drafts.count) saved job(s)." }
            catch { message = "Saved jobs unavailable: \(error)" }
        }
    }
}
