import SwiftUI
import PhotosUI
import UniformTypeIdentifiers

struct PhotoView: View {
    @State private var selection: PhotosPickerItem?
    @State private var source: Data?
    @State private var result: PreparedPhoto?
    @State private var layout: PhotoLayout = .preserve
    @State private var quality = 100
    @State private var guide = true
    @State private var message = "Choose a photo to prepare it offline."
    @State private var generation = UUID()
    @State private var busy = false
    @State private var exporting = false

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                PhotosPicker("Choose photo", selection: $selection, matching: .images)
                    .buttonStyle(.borderedProminent)
                Picker("Layout", selection: $layout) {
                    ForEach(PhotoLayout.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                }.pickerStyle(.segmented)
                Picker("JPEG quality", selection: $quality) {
                    Text("High · 90").tag(90)
                    Text("Higher · 95").tag(95)
                    Text("Maximum · 100").tag(100)
                }
                Toggle("Show safe-area guide", isOn: $guide)
                if let result {
                    Image(uiImage: UIImage(cgImage: result.preview))
                        .resizable().aspectRatio(2.0/3, contentMode: .fit)
                        .overlay {
                            if guide {
                                GeometryReader { proxy in
                                    Rectangle().stroke(.purple, style: StrokeStyle(lineWidth: 2, dash: [6,4]))
                                        .frame(width: proxy.size.width * 672/768, height: proxy.size.height * 1056/1152)
                                        .position(x: proxy.size.width/2, y: proxy.size.height/2)
                                }.allowsHitTesting(false)
                            }
                        }
                    Button("Save prepared JPEG to Files") { exporting = true }.buttonStyle(.bordered)
                    Text("768 × 1152 · \(result.jpeg.count.formatted()) bytes").font(.caption)
                }
                if busy { ProgressView() }
                Text(message).font(.callout)
                Text("The preview shows the decoded JPEG. The purple guide is never included in the image. Preserve edges keeps the whole photo inside a conservative inset; it cannot guarantee exact paper trimming.").font(.caption)
                Text("Apple JPEG quality controls compression strength. Chroma subsampling is selected by the encoder; 100 does not promise 4:4:4 or match the desktop encoder. No PhotoFix is applied.").font(.caption)
                Text("Offline preparation only — no Print or Send action.").font(.headline)
            }.padding()
        }
        .navigationTitle("Prepare photo")
        .fileExporter(isPresented: $exporting, document: PreparedJPEG(data: result?.jpeg ?? Data()), contentType: .jpeg, defaultFilename: "select-prepared") { outcome in
            if case .failure(let error) = outcome { message = error.localizedDescription }
        }
        .onChange(of: selection) { item in
            let token = UUID(); generation = token; result = nil; source = nil; busy = true
            Task {
                do {
                    guard let data = try await item?.loadTransferable(type: Data.self) else { throw PhotoPreparation.Failure.invalid }
                    guard generation == token else { return }
                    source = data; render()
                } catch {
                    guard generation == token else { return }
                    busy = false; message = error.localizedDescription
                }
            }
        }
        .onChange(of: layout) { _ in render() }
        .onChange(of: quality) { _ in render() }
    }
    private func render() {
        guard let source else { return }
        let token = UUID(); generation = token; busy = true; result = nil
        let selectedLayout = layout, selectedQuality = quality
        Task {
            let output = await PhotoRenderer.shared.prepare(source, layout: selectedLayout, quality: selectedQuality)
            guard generation == token else { return }
            busy = false
            switch output {
            case .success(let prepared):
                result = prepared
                message = "Orientation applied; rendered to an 8-bit sRGB canvas on white."
            case .failure(let error): message = error.localizedDescription
            }
        }
    }
}


struct PreparedJPEG: FileDocument {
    static var readableContentTypes: [UTType] { [.jpeg] }
    let data: Data
    init(data: Data) { self.data = data }
    init(configuration: ReadConfiguration) throws { data = configuration.file.regularFileContents ?? Data() }
    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper {
        FileWrapper(regularFileWithContents: data)
    }
}
