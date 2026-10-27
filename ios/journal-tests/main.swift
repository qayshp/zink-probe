import Foundation
import SQLite3
import Darwin

let jpeg = Data([255,216] + Array(repeating: UInt8(42), count: 30) + [255,217])
let id = UUID(uuidString: "00000000-0000-0000-0000-000000000001")!
func job(_ journal: JobJournal, _ identifier: UUID = id) throws -> TrackedUpload {
    try TrackedUpload(journal: journal, id: identifier, device: "test-select", jpeg: jpeg, maximum: 32, name: "Test", nameLimit: 64)
}
func refused(_ block: () throws -> Void) { do { try block(); fatalError("Expected refusal") } catch {} }
let args = CommandLine.arguments
if args.count == 3 && args[1] == "claim" {
    do { let journal = try JobJournal(url: URL(fileURLWithPath: args[2])); _ = try job(journal, UUID()); _exit(0) }
    catch { _exit(2) }
}
if args.count == 4 && args[1] == "crash" {
    let journal = try JobJournal(url: URL(fileURLWithPath: args[2]))
    let upload = try job(journal)
    var point = 0
    let target = Int(args[3])!
    func crashPoint() { if point == target { _exit(0) }; point += 1 }
    crashPoint() // claim committed, no request
    _ = try upload.nextMessage(); crashPoint() // request committed, maybe sent
    try upload.accept([13,7,1,0]); crashPoint()
    _ = try upload.nextMessage(); crashPoint()
    try upload.accept([49]); crashPoint()
    _ = try upload.nextMessage(); crashPoint()
    try upload.accept([15,7,1] + UploadPlan.little(30, bytes: 4) + UploadPlan.little(34, bytes: 4)); crashPoint()
    _ = try upload.nextMessage(); crashPoint()
    try upload.accept([15,7,2] + UploadPlan.little(34, bytes: 4) + UploadPlan.little(34, bytes: 4)); crashPoint()
    fatalError("Unreached crash point")
}
let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
defer { try? FileManager.default.removeItem(at: directory) }
for point in 0...8 {
    let url = directory.appendingPathComponent("crash-\(point).sqlite")
    let process = Process(); process.executableURL = URL(fileURLWithPath: args[0])
    process.arguments = ["crash",url.path,String(point)]
    try process.run(); process.waitUntilExit(); assert(process.terminationStatus == 0)
    let recovered = try JobJournal(url: url)
    let listed = try recovered.unresolvedJobs(); assert(listed.count == 1)
    let record = try recovered.record(id)!
    assert(record.digest == JobJournal.digest(jpeg))
    assert(record.byteCount == jpeg.count)
    assert(record.acknowledgedBytes == (point == 8 ? 34 : point >= 6 ? 30 : 0))
    assert((record.pendingDigest != nil) == [1,3,5,7].contains(point))
    let recovery = try recovered.recovery(id)
    assert(recovery.contains("resubmit"))
    refused { _ = try job(recovered) }
    refused { _ = try job(recovered, UUID()) } // new job ID cannot bypass device claim
    let second = try JobJournal(url: url)
    refused { _ = try job(second, UUID()) }
}
// Inject a database write failure before send, then after a successful send.
func inject(_ url: URL, _ enabled: Bool) {
    var db: OpaquePointer?; assert(sqlite3_open(url.path, &db) == SQLITE_OK)
    defer { sqlite3_close(db) }
    let sql = enabled ? "CREATE TRIGGER fail_update BEFORE UPDATE ON jobs BEGIN SELECT RAISE(FAIL, 'injected failure'); END;" : "DROP TRIGGER fail_update"
    assert(sqlite3_exec(db, sql, nil, nil, nil) == SQLITE_OK)
}
for failBeforeSend in [true,false] {
    let url = directory.appendingPathComponent("failure-\(failBeforeSend).sqlite")
    let journal = try JobJournal(url: url); let upload = try job(journal)
    if !failBeforeSend { _ = try upload.nextMessage() }
    inject(url, true)
    if failBeforeSend { refused { _ = try upload.nextMessage() } }
    else { refused { try upload.accept([13,7,1,0]) } }
    refused { _ = try upload.nextMessage() }
    inject(url, false)
    let reopened = try JobJournal(url: url)
    let record = try reopened.record(id)!
    assert(record.state == (failBeforeSend ? "claimed" : "request_pending"))
    refused { _ = try job(reopened, UUID()) }
}
let url = directory.appendingPathComponent("stop.sqlite")
let journal = try JobJournal(url: url); let upload = try job(journal)
_ = try upload.nextMessage(); upload.stop()
let stoppedRecord = try journal.record(id)!
assert(stoppedRecord.state == "uncertain")
refused { _ = try upload.nextMessage() }
let corrupt = directory.appendingPathComponent("corrupt.sqlite")
try Data("not a database".utf8).write(to: corrupt)
refused { _ = try JobJournal(url: corrupt) }
print("Durable job checks passed: 9 abrupt process exits, restart/duplicate claims, storage failures, uncertain stop, corruption")

let raceURL = directory.appendingPathComponent("race.sqlite")
let setup = try JobJournal(url: raceURL)
var racers: [Process] = []
for _ in 0..<2 {
    let child = Process(); child.executableURL = URL(fileURLWithPath: args[0]); child.arguments = ["claim",raceURL.path]
    try child.run(); racers.append(child)
}
for child in racers { child.waitUntilExit() }
assert(racers.map { $0.terminationStatus }.sorted() == [0,2])
let raceRecords = try setup.unresolvedJobs(); assert(raceRecords.count == 1)
print("Competing processes: exactly one device claim succeeded")
