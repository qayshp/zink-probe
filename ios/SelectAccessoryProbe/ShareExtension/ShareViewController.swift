import UIKit
import SwiftUI
import UniformTypeIdentifiers

final class ShareViewController: UIViewController {
    private var loaded = false
    private let connection = ShareConnectionProbe()
    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        guard !loaded else { return }; loaded = true
        let items = extensionContext?.inputItems as? [NSExtensionItem] ?? []
        let providers = items.flatMap { $0.attachments ?? [] }.filter { $0.hasItemConformingToTypeIdentifier(UTType.image.identifier) }
        guard providers.count == 1, let provider = providers.first else {
            showError("Share one photo at a time."); return
        }
        let type = provider.registeredTypeIdentifiers.first { UTType($0)?.conforms(to: .image) == true } ?? UTType.image.identifier
        provider.loadDataRepresentation(forTypeIdentifier: type) { [weak self] data, error in
            DispatchQueue.main.async {
                guard let self else { return }
                guard let data, data.count <= 50_000_000 else {
                    self.showError(error?.localizedDescription ?? "Image unavailable or larger than 50 MB."); return
                }
                let connection = self.connection
                self.presentContent(SharePhotoFlow(initialData:data,connection:connection).toolbar {
                    ToolbarItem(placement: .primaryAction) {
                        NavigationLink("Connection test") { ShareConnectionView(probe: connection) }
                    }
                })
            }
        }
    }
    override func viewDidDisappear(_ animated: Bool) {
        super.viewDidDisappear(animated)
        connection.stop("Share extension dismissed")
    }
    private func showError(_ text: String) { presentContent(Text(text).padding()) }
    private func presentContent<V: View>(_ content: V) {
        let host = UIHostingController(rootView: NavigationStack {
            content.toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Done") { [weak self] in self?.connection.stop("Share extension completed"); self?.extensionContext?.completeRequest(returningItems: nil) }
                }
            }
        })
        addChild(host); host.view.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(host.view)
        NSLayoutConstraint.activate([host.view.leadingAnchor.constraint(equalTo: view.leadingAnchor),host.view.trailingAnchor.constraint(equalTo:view.trailingAnchor),host.view.topAnchor.constraint(equalTo:view.topAnchor),host.view.bottomAnchor.constraint(equalTo:view.bottomAnchor)])
        host.didMove(toParent: self)
    }
}
