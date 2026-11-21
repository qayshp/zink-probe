import SwiftUI

@main
struct BLEOnlyProbeApp: App {
    var body: some Scene {
        WindowGroup {
            NavigationStack {
                #if ZINK_EXPERIMENTAL_BLE_PRINT
                List {
                    Section {
                        NavigationLink("Prepare one BLE print") { pilotView }
                    } footer: {
                        Text("Choose and preview a photo, check your Select, then confirm one sheet.")
                    }
                    Section("Diagnostics") {
                        NavigationLink("Run read-only BLE check") {
                            BLEProbeView(context: "BLE-only main app")
                        }
                    }
                }
                .navigationTitle("Select BLE Pilot")
                #else
                BLEProbeView(context: "BLE-only main app")
                #endif
            }
        }
    }

    #if ZINK_EXPERIMENTAL_BLE_PRINT
    @ViewBuilder private var pilotView: some View {
        #if DEBUG && targetEnvironment(simulator)
        if let fixture = BLEPilotSimulatorFixture.fromEnvironment() {
            BLEPilotView(adapter: fixture.adapter, fixturePhoto: fixture.photo,
                         selection: fixture.selection, storageRoot: fixture.storageRoot)
        } else {
            BLEPilotView()
        }
        #else
        BLEPilotView()
        #endif
    }
    #endif
}
