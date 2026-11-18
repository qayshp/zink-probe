import SwiftUI

/// Control experiment: this product has no External Accessory declarations,
/// submission core, saved drafts, image handling or printing code.
@main
struct BLEOnlyProbeApp: App {
    var body: some Scene {
        WindowGroup {
            NavigationStack {
                BLEProbeView(context: "BLE-only main app")
            }
        }
    }
}
