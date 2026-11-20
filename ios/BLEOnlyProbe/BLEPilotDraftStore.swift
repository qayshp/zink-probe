import Foundation

/// A prepared photo waiting for printer verification. This record carries no
/// printer identity and is never a print permit or a job binding. A newly
/// prepared version of a photo has a new ID.
struct BLEPilotDraft {
    let id: UUID
    let image: PreparedJobImage
    let settings: JobBinding.Settings
}

/// Holds one unbound draft in the app's private directory. The app serializes
/// calls on its main actor and supplies an existing, backup-excluded directory.
struct BLEPilotDraftStore {
    private struct Record: Codable {
        let version: Int
        let id: UUID
        let jpeg: Data
        let digest: String
        let settings: JobBinding.Settings
    }

    enum Failure: LocalizedError {
        case invalidDraft

        var errorDescription: String? { "The saved photo draft could not be verified." }
    }

    // The prepared image validator permits a 16 MiB JPEG. A binary plist
    // stores those bytes directly, with room here for its versioned envelope.
    private static let maximumFileBytes = 16 * 1024 * 1024 + 4096
    let url: URL

    func load() throws -> BLEPilotDraft? {
        guard let record = try readRecord() else { return nil }
        let image = try PreparedJobImage(jpeg: record.jpeg)
        return BLEPilotDraft(id: record.id, image: image, settings: record.settings)
    }

    func save(_ draft: BLEPilotDraft) throws {
        guard draft.settings.valid else { throw Failure.invalidDraft }
        let record = Record(version: 1, id: draft.id, jpeg: draft.image.jpeg,
                            digest: JobJournal.digest(draft.image.jpeg), settings: draft.settings)
        let encoder = PropertyListEncoder()
        encoder.outputFormat = .binary
        let bytes = try encoder.encode(record)
        guard bytes.count <= Self.maximumFileBytes else { throw Failure.invalidDraft }
        #if os(iOS)
        try bytes.write(to: url, options: [.atomic, .completeFileProtection])
        #else
        try bytes.write(to: url, options: .atomic)
        #endif
    }

    /// A printer check finishing for an earlier draft must leave a replacement
    /// photo intact. The ID test and removal run together on the app's actor.
    func discard(id: UUID) throws {
        guard try readRecord()?.id == id else { return }
        try FileManager.default.removeItem(at: url)
    }

    private func readRecord() throws -> Record? {
        let handle: FileHandle
        do {
            handle = try FileHandle(forReadingFrom: url)
        } catch let error as CocoaError where error.code == .fileNoSuchFile || error.code == .fileReadNoSuchFile {
            return nil
        }
        defer { try? handle.close() }

        let size = try handle.seekToEnd()
        guard size > 0, size <= UInt64(Self.maximumFileBytes) else { throw Failure.invalidDraft }
        try handle.seek(toOffset: 0)
        guard let bytes = try handle.read(upToCount: Int(size) + 1), bytes.count == Int(size),
              let record = try? PropertyListDecoder().decode(Record.self, from: bytes),
              record.version == 1, record.settings.valid,
              JobJournal.digest(record.jpeg) == record.digest else { throw Failure.invalidDraft }
        return record
    }
}
