import UIKit
import SwiftUI

/// Deliberately ignores the shared image. Opening this controller performs no
/// Bluetooth operation; the common view requires explicit scan and check taps.
final class ShareViewController: UIViewController {
    private var hosted = false
    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        guard !hosted else { return }
        hosted = true
        let host = UIHostingController(rootView: NavigationStack {
            BLEProbeView(context: "BLE-only Share extension")
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("Done") { [weak self] in
                            self?.extensionContext?.completeRequest(returningItems: nil)
                        }
                    }
                }
        })
        addChild(host)
        host.view.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(host.view)
        NSLayoutConstraint.activate([
            host.view.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            host.view.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            host.view.topAnchor.constraint(equalTo: view.topAnchor),
            host.view.bottomAnchor.constraint(equalTo: view.bottomAnchor)
        ])
        host.didMove(toParent: self)
    }
}
