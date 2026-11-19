import SwiftUI

@main
struct BLEOnlyProbeApp: App {
    var body: some Scene {
        WindowGroup {
            NavigationStack {
                #if ZINK_EXPERIMENTAL_BLE_PRINT
                List {
                    NavigationLink("Prepare one BLE print") { BLEPilotView() }
                    NavigationLink("Run read-only BLE check") {
                        BLEProbeView(context: "BLE-only main app")
                    }
                }
                .navigationTitle("Select BLE Pilot")
                #else
                BLEProbeView(context: "BLE-only main app")
                #endif
            }
        }
    }
}
