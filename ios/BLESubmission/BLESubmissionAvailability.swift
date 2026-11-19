import Foundation

/// A deliberate build-time boundary, not a user preference or runtime switch.
/// Simulations compose the existing permit-gated coordinator with an in-memory
/// packet IO. Native submission must stop before reserving a permit or radio.
enum BLESubmissionAvailability {
    #if ZINK_EXPERIMENTAL_BLE_PRINT
    static let isEnabled = true
    #else
    static let isEnabled = false
    #endif

    enum Failure: Error, CustomStringConvertible {
        case liveSubmissionDisabled
        var description: String {
            "Real BLE submission is disabled in this build. No print authorization or Bluetooth connection was created."
        }
    }
    static func requireLiveSubmission() throws {
        guard isEnabled else { throw Failure.liveSubmissionDisabled }
    }
}
