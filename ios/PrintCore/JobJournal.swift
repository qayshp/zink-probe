import Foundation
import CryptoKit
import SQLite3

/// Serial-use SQLite journal. All entry points run synchronously; do not share
/// an instance across threads. Separate instances/processes serialize via SQLite.
final class JobJournal {
    enum Failure: Error { case storage(String), blocked, invalidRecord }
    struct Record: Codable {
        let id: UUID
        let device: String
        let digest: String
        let byteCount: Int
        var state: String
        var pendingDigest: String?
        var pendingOpcode: UInt8?
        var acknowledgedBytes: Int
        var printerJobID: UInt16?
        var handle: UInt8?
    }
    private var db: OpaquePointer?
    init(url: URL) throws {
        guard sqlite3_open_v2(url.path, &db, SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_FULLMUTEX, nil) == SQLITE_OK else {
            if let db { sqlite3_close(db) }; db = nil
            throw Failure.storage("Cannot open job journal")
        }
        do {
            try sql("PRAGMA synchronous=FULL")
            try sql("PRAGMA journal_mode=DELETE")
            try sql("PRAGMA busy_timeout=2000")
            // No release path yet: every existing device claim remains blocked.
            try sql("CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, device TEXT NOT NULL UNIQUE, record TEXT NOT NULL)")
        } catch { sqlite3_close(db); db = nil; throw error }
    }
    deinit { sqlite3_close(db) }
    static func digest(_ bytes: Data) -> String { SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined() }
    private func quote(_ text: String) -> String { "'" + text.replacingOccurrences(of: "'", with: "''") + "'" }
    private func sql(_ query: String) throws {
        guard sqlite3_exec(db, query, nil, nil, nil) == SQLITE_OK else { throw Failure.storage(String(cString: sqlite3_errmsg(db))) }
    }
    private func transaction<T>(_ body: () throws -> T) throws -> T {
        try sql("BEGIN IMMEDIATE")
        do { let result = try body(); try sql("COMMIT"); return result }
        catch { try? sql("ROLLBACK"); throw error }
    }
    private func encoded(_ record: Record) throws -> String {
        String(decoding: try JSONEncoder().encode(record), as: UTF8.self)
    }
    func record(_ id: UUID) throws -> Record? {
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(db, "SELECT record FROM jobs WHERE id=\(quote(id.uuidString))", -1, &statement, nil) == SQLITE_OK else { throw Failure.storage("Cannot read journal") }
        defer { sqlite3_finalize(statement) }
        let code = sqlite3_step(statement)
        if code == SQLITE_DONE { return nil }
        guard code == SQLITE_ROW, let text = sqlite3_column_text(statement, 0) else { throw Failure.invalidRecord }
        let result = try JSONDecoder().decode(Record.self, from: Data(String(cString: text).utf8))
        guard result.id == id else { throw Failure.invalidRecord }
        return result
    }
    fileprivate func claim(id: UUID, device: String, jpeg: Data) throws {
        guard !device.isEmpty, !device.contains("\0") else { throw Failure.invalidRecord }
        try transaction {
            let record = Record(id: id, device: device, digest: Self.digest(jpeg), byteCount: jpeg.count,
                                state: "claimed", acknowledgedBytes: 0)
            try sql("INSERT INTO jobs VALUES(\(quote(id.uuidString)),\(quote(device)),\(quote(try encoded(record))))")
        }
    }
    fileprivate func update(_ id: UUID, _ change: (inout Record) throws -> Void) throws {
        try transaction {
            guard var record = try record(id) else { throw Failure.invalidRecord }
            try change(&record)
            try sql("UPDATE jobs SET record=\(quote(try encoded(record))) WHERE id=\(quote(id.uuidString))")
        }
    }
    func unresolvedJobs() throws -> [Record] {
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(db, "SELECT id FROM jobs ORDER BY id", -1, &statement, nil) == SQLITE_OK else { throw Failure.storage("Cannot list journal") }
        defer { sqlite3_finalize(statement) }
        var results: [Record] = []
        while true {
            let code = sqlite3_step(statement)
            if code == SQLITE_DONE { return results }
            guard code == SQLITE_ROW, let text = sqlite3_column_text(statement, 0),
                  let id = UUID(uuidString: String(cString: text)), let item = try record(id) else { throw Failure.invalidRecord }
            results.append(item)
        }
    }
    /// Observation only: reopening never constructs an upload plan or grants a send permit.
    func recovery(_ id: UUID) throws -> String {
        guard let record = try record(id) else { throw Failure.invalidRecord }
        return record.state == "uploaded" ? "Upload acknowledged; physical outcome unconfirmed. Do not resubmit."
            : "Unresolved job (\(record.state)); do not resubmit. Read-only reconciliation required."
    }
}

/// Owns the only live plan for a newly claimed job. No restore/resume constructor.
/// Call nextMessage immediately before writing; bytes are returned only after commit.
final class TrackedUpload {
    let id: UUID
    private let journal: JobJournal
    private var plan: UploadPlan
    private var stopped = false
    init(journal: JobJournal, id: UUID, device: String, jpeg: Data, maximum: Int, name: String, nameLimit: Int) throws {
        let plan = try UploadPlan(preparedJPEG: jpeg, maximum: maximum, name: name, nameLimit: nameLimit)
        try journal.claim(id: id, device: device, jpeg: jpeg)
        self.journal = journal; self.id = id; self.plan = plan
    }
    func nextMessage() throws -> [UInt8] {
        guard !stopped else { throw JobJournal.Failure.blocked }
        do {
            let message = try plan.nextMessage()
            try journal.update(id) { record in
                guard record.pendingDigest == nil else { throw JobJournal.Failure.blocked }
                record.state = "request_pending"
                record.pendingDigest = JobJournal.digest(Data(message)); record.pendingOpcode = message[0]
            }
            return message
        } catch { stopped = true; plan.stop(); throw error }
    }
    func accept(_ reply: [UInt8]) throws {
        guard !stopped else { throw JobJournal.Failure.blocked }
        do {
            try plan.accept(reply)
            try journal.update(id) { record in
                guard record.pendingDigest != nil else { throw JobJournal.Failure.blocked }
                record.state = plan.phase == .uploaded ? "uploaded" : "acknowledged"
                record.pendingDigest = nil; record.pendingOpcode = nil
                record.acknowledgedBytes = plan.offset; record.printerJobID = plan.jobID; record.handle = plan.handle
            }
        } catch { stop(); throw error }
    }
    /// Preserve pending evidence even if writing the uncertain state fails.
    func stop() {
        stopped = true; plan.stop()
        try? journal.update(id) { $0.state = "uncertain" }
    }
}
