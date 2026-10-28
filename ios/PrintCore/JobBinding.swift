import Foundation

/// Immutable persisted draft metadata. Saving a binding never authorizes printing.
struct JobBinding: Codable, Equatable, Identifiable, Sendable {
    struct Settings: Codable, Equatable, Sendable {
        let layout: String
        let quality: Int
        var valid: Bool { ["Borderless","Fit","Preserve edges"].contains(layout) && [90,95,100].contains(quality) }
    }
    let id: UUID
    let device: String
    let firmware: String
    let digest: String
    let byteCount: Int
    let sampling: String
    let settings: Settings
    let checkedAt: Date
    let schema: Int
    var valid: Bool {
        schema == 1 && device.count == 32 && device.allSatisfy { "0123456789abcdef".contains($0) }
            && !firmware.isEmpty && digest.count == 64 && digest.allSatisfy { "0123456789abcdef".contains($0) }
            && (4...16*1024*1024).contains(byteCount) && ["4:4:4","4:2:2","4:2:0"].contains(sampling)
            && settings.valid && checkedAt.timeIntervalSince1970.isFinite
    }
}
