import SwiftUI
import UIKit

/// Immutable review: subsequent editor changes cannot alter this job's bytes.
struct PreparedPhotoReview: Identifiable {
    let id = UUID()
    let jpeg: Data
    let preview: CGImage
    let layout: String
    let quality: Int
    init(photo: PreparedPhoto, layout: PhotoLayout, quality: Int) {
        jpeg = photo.jpeg; preview = photo.preview; self.layout = layout.rawValue; self.quality = quality
    }
}

struct SimulationPhotoFlow: View {
    let initialData: Data
    @State private var review: PreparedPhotoReview?
    var body: some View {
        PhotoView(initialData:initialData,onReview:{ photo,layout,quality in
            review = PreparedPhotoReview(photo:photo,layout:layout,quality:quality)
        })
        .sheet(item:$review) { item in SimulationConfirmationView(review:item) }
    }
}

@MainActor
final class SimulationViewModel: ObservableObject {
    @Published var snapshot: SimulationSnapshot
    private let driver: SimulatedSubmission
    private var task: Task<Void,Never>?
    private var observer: NSObjectProtocol?
    init(review: PreparedPhotoReview) {
        snapshot = SimulationSnapshot(totalBytes:review.jpeg.count)
        let root = FileManager.default.urls(for:.applicationSupportDirectory,in:.userDomainMask)[0]
        let store = root.appendingPathComponent("SelectSimulation/SIMULATION-ONLY.sqlite")
        driver = SimulatedSubmission(id:review.id,jpeg:review.jpeg,journalURL:store)
        observer = NotificationCenter.default.addObserver(forName:.NSExtensionHostWillResignActive,object:nil,queue:.main) { [weak self] _ in
            Task { @MainActor [weak self] in self?.cancel() }
        }
    }
    deinit { task?.cancel(); if let observer { NotificationCenter.default.removeObserver(observer) } }
    func confirm(_ scenario: SimulationScenario) {
        guard !snapshot.running, !snapshot.confirmed else { return }
        run { await self.driver.confirm(scenario:scenario) }
    }
    func recover() {
        guard !snapshot.running, snapshot.confirmed, !snapshot.recoveryAttempted else { return }
        run { await self.driver.recover() }
    }
    private func run(_ start: @escaping () async -> SimulationSnapshot) {
        snapshot.running = true
        task = Task { [weak self] in
            guard let self else { return }
            do {
                try Task.checkCancellation()
                snapshot = await start()
                while snapshot.running {
                    try Task.checkCancellation()
                    snapshot = await driver.advance()
                    try await Task.sleep(nanoseconds:20_000_000)
                }
            } catch { snapshot = await driver.cancel() }
        }
    }
    func cancel() {
        task?.cancel()
        Task { [weak self] in guard let self else { return }; snapshot = await driver.cancel() }
    }
    func duplicateCheck() {
        guard !snapshot.running else { return }
        Task { snapshot = await driver.checkDuplicate() }
    }
}

struct SimulationConfirmationView: View {
    let review: PreparedPhotoReview
    @StateObject private var model: SimulationViewModel
    @State private var scenario: SimulationScenario = .success
    @Environment(\.dismiss) private var dismiss
    init(review: PreparedPhotoReview) {
        self.review = review; _model = StateObject(wrappedValue:SimulationViewModel(review:review))
    }
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment:.leading,spacing:16) {
                    Text("SIMULATION ONLY").font(.headline).foregroundStyle(.orange)
                    Text("Real printing is disabled. Confirming runs this job against an in-memory printer and uses no paper.")
                    Image(uiImage:UIImage(cgImage:review.preview)).resizable().scaledToFit().frame(maxHeight:240).frame(maxWidth:.infinity)
                    Group {
                        LabeledContent("Destination",value:"Simulated Select")
                        LabeledContent("Copies",value:"1")
                        LabeledContent("Layout",value:review.layout)
                        LabeledContent("JPEG quality",value:String(review.quality))
                        LabeledContent("Dimensions",value:"768 × 1152")
                        LabeledContent("File size",value:"\(review.jpeg.count.formatted()) bytes")
                        Text("Color sampling: \(JPEGDetails.sampling(review.jpeg))").font(.caption)
                    }
                    Text("This review freezes the image and settings. Close it to return to editing.").font(.caption)
                    if !model.snapshot.confirmed {
                        Picker("Simulation scenario",selection:$scenario) {
                            ForEach(SimulationScenario.allCases,id:\.self) { Text($0.rawValue).tag($0) }
                        }.disabled(model.snapshot.running)
                        Button("Confirm simulated job") { model.confirm(scenario) }
                            .buttonStyle(.borderedProminent).disabled(model.snapshot.running)
                            .accessibilityIdentifier("confirm-simulated-job")
                    }
                    Text("Real printing disabled in this build").font(.callout)
                        .accessibilityIdentifier("real-printing-disabled")
                    Divider()
                    Text(statusTitle).font(.headline).accessibilityIdentifier("simulation-status")
                    Text(model.snapshot.detail).accessibilityIdentifier("simulation-detail")
                    if model.snapshot.running {
                        ProgressView(value:Double(model.snapshot.acknowledgedBytes),total:Double(max(1,review.jpeg.count)))
                        Button("Stop simulation") { model.cancel() }.buttonStyle(.bordered)
                    }
                    if model.snapshot.confirmed && !model.snapshot.running {
                        Button("Check duplicate protection") { model.duplicateCheck() }.buttonStyle(.bordered)
                            .accessibilityIdentifier("check-duplicate")
                        if model.snapshot.state == "uncertain" && !model.snapshot.recoveryAttempted {
                            Button("Check saved job read-only") { model.recover() }.buttonStyle(.bordered)
                        }
                    }
                    if model.snapshot.duplicateBlocked { Text("Duplicate blocked; no second simulated job was sent.").accessibilityIdentifier("duplicate-blocked") }
                    Text("Acknowledged: \(model.snapshot.acknowledgedBytes) / \(review.jpeg.count) bytes\nSimulated PrintStart count: \(model.snapshot.printStarts)\nReal printer bytes: 0")
                        .font(.system(.caption,design:.monospaced))
                }.padding()
            }
            .navigationTitle("Review simulated job")
            .toolbar { ToolbarItem(placement:.cancellationAction) {
                Button("Close") { model.cancel(); dismiss() }
            } }
        }
        .onDisappear { model.cancel() }
    }
    private var statusTitle: String {
        switch model.snapshot.state {
        case "review": return "Awaiting confirmation"
        case "preflight": return "Simulated preflight"
        case "uploading": return "Simulated upload"
        case "observing", "recovering": return "Checking simulated outcome"
        case "completed": return "Simulation completed"
        case "uncertain": return "Simulated outcome uncertain"
        default: return "Simulation stopped"
        }
    }
}

#if targetEnvironment(simulator)
enum SimulationUIFixture {
    static var png: Data {
        UIGraphicsImageRenderer(size:CGSize(width:768,height:1152)).pngData { context in
            UIColor.white.setFill(); context.fill(CGRect(x:0,y:0,width:768,height:1152))
            ("SELECT SIMULATION\nNo paper used" as NSString).draw(at:CGPoint(x:50,y:100),withAttributes:[.font:UIFont.systemFont(ofSize:42),.foregroundColor:UIColor.black])
        }
    }
}
#endif
