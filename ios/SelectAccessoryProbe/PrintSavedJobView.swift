import SwiftUI

/// Keep result ownership independent of the list row: completion can archive the
/// underlying draft without removing the active confirmation/result screen.
struct PrintSavedJobSheet: View {
    let id: UUID
    @ObservedObject var connection: ShareConnectionProbe
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            PrintSavedJobView(id:id,connection:connection)
                .toolbar { ToolbarItem(placement:.cancellationAction) { Button("Close") { dismiss() } } }
        }
    }
}

/// The only real submission action. Loading/reappearing never submits. Once the
/// user confirms, this view cannot grant another attempt, including after restart.
struct PrintSavedJobView: View {
    let id: UUID
    @ObservedObject var connection: ShareConnectionProbe
    @State private var review: LiveDraftStorage.Review?
    @State private var preview: UIImage?
    @State private var confirmed = false
    @State private var error = ""
    private let storage = LiveDraftStorage()
    var body: some View {
        ScrollView {
            VStack(alignment:.leading,spacing:16) {
                #if targetEnvironment(simulator)
                Text("SIMULATOR · memory printer only").font(.headline).foregroundStyle(.orange)
                #else
                Text("This action prints one physical photo").font(.headline)
                #endif
                if let review {
                    if let preview { Image(uiImage:preview).resizable().scaledToFit().frame(maxHeight:260).frame(maxWidth:.infinity) }
                    Text("One copy · \(review.binding.settings.layout)\nJPEG \(review.binding.settings.quality) · \(review.binding.sampling)\n768 × 1152 · \(review.jpeg.count.formatted()) bytes\nSaved job \(id.uuidString.prefix(8)) · firmware \(review.binding.firmware)")
                    Text("The saved photo shown here is the exact JPEG that will be sent. Fresh preflight must match its bound printer. Keep this screen visible and the phone unlocked until the result is known.")
                    Text("If interrupted, the outcome may be uncertain even if a photo prints. This job will not automatically retry. Stopping the connection cannot promise to stop paper already accepted by the printer.").font(.caption)
                    if !confirmed && review.attempt == nil {
                        Button("Refresh connected printers") { connection.refresh() }.disabled(connection.active)
                        #if targetEnvironment(simulator)
                        Button("Confirm simulated one-copy attempt") { confirmed = true; connection.simulatePrintOnce(review.binding) }
                            .buttonStyle(.borderedProminent).disabled(connection.active).accessibilityIdentifier("confirm-one-print")
                        #else
                        ForEach(connection.accessories,id:\.connectionID) { accessory in
                            Button("Print this photo once to \(accessory.name)") {
                                confirmed = true; connection.submitOnce(accessory,reviewed:review.binding)
                            }.buttonStyle(.borderedProminent).disabled(connection.active)
                                .accessibilityIdentifier("confirm-one-print")
                        }
                        if connection.accessories.isEmpty { Text("No Select connected. Connect it using the main app or iPhone Bluetooth Settings, then refresh.") }
                        #endif
                    } else {
                        Text("Confirmation handled. Check the saved result before taking any further action.").font(.headline).accessibilityIdentifier("print-confirmation-used")
                    }
                    if confirmed && connection.printingJob == id {
                        Text(connection.printState).font(.headline).accessibilityIdentifier("live-print-state")
                        Text(connection.printResult).accessibilityIdentifier("live-print-result")
                        Text("Image acknowledged: \(connection.printAcknowledged.formatted()) / \(connection.printTotal.formatted()) bytes")
                        if connection.active {
                            ProgressView(value:Double(connection.printAcknowledged),total:Double(max(1,connection.printTotal)))
                            Button("Stop connection") { connection.stop("User stopped print connection; physical outcome may be uncertain") }.buttonStyle(.bordered)
                        }
                    }
                    if let attempt = review.attempt { Text("Saved attempt state: \(attempt). Use read-only recovery from Saved printer drafts; do not submit another copy to resolve uncertainty.") }
                } else if error.isEmpty { ProgressView() }
                Text(error)
            }.padding()
        }
        .navigationTitle("Review one-photo print")
        .task {
            do {
                let value = try await storage.review(id)
                guard !Task.isCancelled else { return }
                review = value; preview = UIImage(data:value.jpeg)
            } catch { self.error = "Saved photo could not be verified: \(error)" }
        }
        .onDisappear { connection.stop("Print review closed; no automatic resubmission") }
    }
}
