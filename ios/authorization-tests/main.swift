import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
import SQLite3

func check(_ value: Bool, file: StaticString = #file, line: UInt = #line) { precondition(value,file:file,line:line) }
func refuses(_ body: () throws -> Void) { do { try body(); fatalError("Expected refusal") } catch {} }
func makeJPEG() -> Data {
    let c = CGContext(data:nil,width:768,height:1152,bitsPerComponent:8,bytesPerRow:0,space:CGColorSpace(name:CGColorSpace.sRGB)!,bitmapInfo:CGImageAlphaInfo.noneSkipLast.rawValue)!
    c.setFillColor(CGColor(gray:0.5,alpha:1)); c.fill(CGRect(x:0,y:0,width:768,height:1152))
    let d = NSMutableData(), out = CGImageDestinationCreateWithData(d,UTType.jpeg.identifier as CFString,1,nil)!
    CGImageDestinationAddImage(out,c.makeImage()!,[kCGImageDestinationLossyCompressionQuality:1] as CFDictionary)
    precondition(CGImageDestinationFinalize(out)); return d as Data
}
let image = try PreparedJobImage(jpeg:makeJPEG()), settings = JobBinding.Settings(layout:"Preserve edges",quality:100)
func verify(_ peer: SimulatedPrinter = SimulatedPrinter(), now: TimeInterval = 0) throws -> VerifiedPrinter {
    var reader = try ReadOnlyPreflight()
    while !reader.complete { try reader.accept(peer.respond(reader.next())) }
    return try VerifiedPrinter(preflight:reader,expectedFirmware:peer.firmware,now:now,date:Date(timeIntervalSince1970:now))
}
func save(_ journal: JobJournal, id: UUID = UUID()) throws -> JobBinding {
    try journal.bind(id:id,image:image,settings:settings,printer:verify(),now:0)
}
final class Time { var now = 0.0 }
final class IO: AccessoryDuplex {
    let peer: SimulatedPrinter
    var closed = false, closeCount = 0, total = 0, limit = 127, readLimit = 257
    var cut: Int?
    init(_ peer: SimulatedPrinter = SimulatedPrinter()) { self.peer = peer }
    var hasBytes: Bool { !closed && !peer.output.isEmpty }
    var hasSpace: Bool { !closed }
    func open(_ handler: @escaping (AccessoryIOEvent) -> Void) { handler(.opened(.input)); handler(.opened(.output)) }
    func read(maximum: Int) -> AccessoryRead {
        guard hasBytes else { return .wouldBlock }
        let count = min(maximum,readLimit,peer.output.count), bytes = Array(peer.output.prefix(count)); peer.output.removeFirst(count); return .bytes(bytes)
    }
    func write(_ bytes: [UInt8]) -> Int {
        if let cut, total >= cut { return -1 }
        let count = peer.write(bytes,limit:min(limit,cut.map { $0-total } ?? Int.max)); total += count; return count
    }
    func close() { closeCount += 1; closed = true }
}
func drive(_ driver: AccessoryStreamDriver, _ clock: Time) {
    driver.start()
    for _ in 0..<400000 { if driver.closed { return }; clock.now += 0.001; driver.tick() }
    fatalError("Attempt failed to terminate")
}
func authorized(_ binding: JobBinding, _ store: JobJournal, _ clock: Time) throws -> (AccessoryStreamPump,PrintPermit) {
    let permit = try store.authorizePrintOnce(binding)
    let coordinator = try SubmissionCoordinator(boundJob:binding.id,journal:store,now:clock.now,pollInterval:0.01,authorization:permit)
    return (try AccessoryStreamPump(coordinator:coordinator,permit:permit,journal:store,now:clock.now),permit)
}
func stopBeforeSubmission(_ binding: JobBinding, _ journal: JobJournal) throws {
    let peer = SimulatedPrinter()
    peer.paused = true
    let clock = Time(), (pump,_) = try authorized(binding,journal,clock)
    let driver = AccessoryStreamDriver(pump:pump,io:IO(peer),clock:{ clock.now },update:{ _ in })
    drive(driver,clock)
    check(peer.mutationCount == 0 && !pump.succeeded)
    check(try journal.attemptState(binding.id) == "notSubmitted" && journal.record(binding.id) == nil)
}
let fixedID = UUID(uuidString:"55555555-5555-4555-8555-555555555555")!
if CommandLine.arguments.count == 3 {
    let mode = CommandLine.arguments[1], store = try JobJournal(url:URL(fileURLWithPath:CommandLine.arguments[2]))
    if mode == "prepare" { _ = try save(store,id:fixedID); print("Synthetic draft prepared; no authorization issued."); exit(0) }
    if mode == "race" {
        do { let binding = try store.binding(fixedID)!; _ = try store.authorizePrintOnce(binding); _exit(0) } catch { _exit(2) }
    }
    if mode == "race-new-draft" {
        let printer = try verify()
        do { _ = try store.prepareNewAttempt(from:fixedID,newID:UUID(),printer:printer,now:0); _exit(0) }
        catch JobJournal.Failure.blocked { _exit(2) }
    }
    let b = try save(store,id:fixedID), token = try store.authorizePrintOnce(b)
    if mode == "authorized" { _exit(0) }
    let clock = Time(), coordinator = try SubmissionCoordinator(boundJob:b.id,journal:store,now:0,pollInterval:0.01,authorization:token)
    let pump = try AccessoryStreamPump(coordinator:coordinator,permit:token,journal:store,now:0)
    if mode == "started" { _exit(0) }
    let io = IO(), driver = AccessoryStreamDriver(pump:pump,io:io,clock:{ clock.now },update:{ _ in }); driver.start()
    for _ in 0..<400000 {
        clock.now += 0.001; driver.tick()
        let record = try store.record(b.id)
        if mode == "pending" && record?.pendingOpcode == 12 { _exit(0) }
        if mode == "uploaded" && record?.uploadAcknowledged == true { _exit(0) }
        if mode == "completed" && pump.succeeded { _exit(0) }
        if driver.closed { break }
    }
    fatalError("Crash boundary not reached")
}
let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
defer { try? FileManager.default.removeItem(at:root) }
func store(_ name: String) throws -> JobJournal { try JobJournal(url:root.appendingPathComponent(name+".sqlite")) }
for empty in [false,true] {
    let j = try store("success-\(empty)"), b = try save(j), clock = Time(), peer = SimulatedPrinter()
    peer.requireEmptyFinal = empty
    let (pump,token) = try authorized(b,j,clock), io = IO(peer); io.limit = empty ? 1 : 127; io.readLimit = empty ? 1 : 257
    refuses { _ = try j.authorizePrintOnce(b) }; refuses { try token.consume(in:j) }
    let driver = AccessoryStreamDriver(pump:pump,io:io,clock:{ clock.now },update:{ _ in }); drive(driver,clock)
    check(pump.succeeded && peer.startCount == 1 && Data(peer.uploadedData) == image.jpeg && io.closeCount == 1)
    check(try j.attemptState(b.id) == "completed"); check(try j.activeBindings().isEmpty)
    refuses { _ = try j.authorizePrintOnce(b) }; refuses { _ = try SubmissionCoordinator(boundJob:b.id,journal:j,now:clock.now) }
    let before = io.total; driver.start(); driver.tick(); check(io.total == before)
}
for fault in ["start","properties","final","identity","pause","cancel","disconnect"] {
    let j = try store(fault), b = try save(j), clock = Time(), peer = SimulatedPrinter()
    if fault == "start" { peer.droppedOpcode = 12 }
    if fault == "properties" { peer.droppedOpcode = 48 }
    peer.dropFinalAck = fault == "final"; peer.mismatchIdentity = fault == "identity"; peer.paused = fault == "pause"
    let (pump,_) = try authorized(b,j,clock), io = IO(peer), driver = AccessoryStreamDriver(pump:pump,io:io,clock:{ clock.now },update:{ _ in })
    driver.start()
    if ["cancel","disconnect"].contains(fault) {
        for _ in 0..<10000 {
            clock.now += 0.001; driver.tick()
            if peer.startCount == 1 { driver.cancel("Interrupted immediately after PrintStart acceptance"); break }
        }
    }
    drive(driver,clock)
    check(!pump.succeeded && peer.startCount <= 1 && io.closeCount == 1)
    let early = ["identity","pause"].contains(fault)
    check(try j.attemptState(b.id) == (early ? "notSubmitted" : "uncertain"))
    refuses { _ = try j.authorizePrintOnce(b) }; refuses { _ = try SubmissionCoordinator(boundJob:b.id,journal:j,now:clock.now) }
    if early { try j.discardDraft(b.id); check(peer.mutationCount == 0) }
    else {
        refuses { try j.discardDraft(b.id) }
        if fault == "final" {
            peer.output = []; peer.input = []; peer.dropFinalAck = false
            let recover = try SubmissionCoordinator(recover:b.id,journal:j,now:clock.now,timeout:1,pollInterval:0.01)
            let recoveryPump = AccessoryStreamPump(coordinator:recover,now:clock.now), recoveryIO = IO(peer), starts = peer.startCount, mutations = peer.mutationCount
            let recoveryDriver = AccessoryStreamDriver(pump:recoveryPump,io:recoveryIO,clock:{ clock.now },update:{ _ in }); drive(recoveryDriver,clock)
            check(peer.startCount == starts && peer.mutationCount == mutations && !recoveryPump.succeeded)
        }
    }
}
// Every prefix of the first mutating frame: a claim is durable even at zero bytes.
for prefix in 0..<11 {
    let j = try store("prefix-\(prefix)"), b = try save(j), clock = Time(), (pump,_) = try authorized(b,j,clock), io = IO()
    io.cut = 77+prefix
    let driver = AccessoryStreamDriver(pump:pump,io:io,clock:{ clock.now },update:{ _ in }); drive(driver,clock)
    check(!pump.succeeded && io.peer.startCount == 0 && io.total == 77+prefix)
    check(try j.record(b.id)?.pendingOpcode == 12); check(try j.attemptState(b.id) == "uncertain")
    refuses { _ = try j.authorizePrintOnce(b) }; refuses { try j.discardDraft(b.id) }
}
// Review mismatch and durable-commit failure cannot issue a token.
let bad = try store("wrong-review"), original = try save(bad)
let different = JobBinding(id:original.id,device:original.device,firmware:original.firmware,digest:original.digest,byteCount:original.byteCount,sampling:original.sampling,settings:.init(layout:"Fit",quality:95),checkedAt:original.checkedAt,schema:1)
refuses { _ = try bad.authorizePrintOnce(different) }; check(try bad.attemptState(original.id) == nil)
let failURL = root.appendingPathComponent("storage.sqlite"), fail = try JobJournal(url:failURL), failBinding = try save(fail)
var db: OpaquePointer?; check(sqlite3_open(failURL.path,&db) == SQLITE_OK)
check(sqlite3_exec(db,"CREATE TRIGGER stop_permit BEFORE INSERT ON print_attempts BEGIN SELECT RAISE(FAIL,'injected'); END",nil,nil,nil) == SQLITE_OK); sqlite3_close(db)
refuses { _ = try fail.authorizePrintOnce(failBinding) }; check(try fail.attemptState(failBinding.id) == nil)
// Gate failure on a fresh session: no second use of a consumed permit.
let once = try store("once"), onceBinding = try save(once), oncePermit = try once.authorizePrintOnce(onceBinding)
_ = try SingleJobFrameGate(permit:oncePermit,journal:once)
refuses { _ = try SingleJobFrameGate(permit:oncePermit,journal:once) }
for op: UInt8 in [12,14,48,24,28,10] {
    let fresh = try store("forbidden-\(op)"), binding = try save(fresh), permit = try fresh.authorizePrintOnce(binding)
    var gate = try SingleJobFrameGate(permit:permit,journal:fresh), written = 0
    refuses { _ = try gate.write(SimulatedPrinter.frame([op,0,0])) { written += $0.count; return $0.count } }
    check(written == 0)
}
func child(_ mode: String, _ url: URL) throws -> Process {
    let p = Process(); p.executableURL = URL(fileURLWithPath:CommandLine.arguments[0]); p.arguments = [mode,url.path]; try p.run(); return p
}
for boundary in ["authorized","started","pending","uploaded","completed"] {
    let url = root.appendingPathComponent("crash-\(boundary).sqlite"), p = try child(boundary,url); p.waitUntilExit(); check(p.terminationStatus == 0)
    let reopened = try JobJournal(url:url), binding = try reopened.binding(fixedID)!
    refuses { _ = try reopened.authorizePrintOnce(binding) }; refuses { _ = try SubmissionCoordinator(boundJob:fixedID,journal:reopened,now:0) }
    refuses { try reopened.discardDraft(fixedID) }
    refuses { _ = try reopened.prepareNewAttempt(from:fixedID,newID:UUID(),printer:verify(),now:0) }
    let summary = try reopened.latestPrintAttempt()!
    check(summary.id == fixedID && summary.status == (boundary == "completed" ? .completed : .uncertain))
    check(summary.report.contains("BLE session diagnostics were unavailable"))
    if boundary == "completed" { check(try reopened.activeBindings().isEmpty) }
}
let raceURL = root.appendingPathComponent("race.sqlite"), race = try JobJournal(url:raceURL); _ = try save(race,id:fixedID)
let a = try child("race",raceURL), b = try child("race",raceURL); a.waitUntilExit(); b.waitUntilExit()
check([a.terminationStatus,b.terminationStatus].sorted() == [0,2])

// Retain a deliberately stopped print attempt after its photo was discarded.
// New drafts do not hide the last attempt. Confirmation order is not UUID order.
let historyURL = root.appendingPathComponent("history.sqlite")
let history = try JobJournal(url:historyURL)
let oldest = try save(history,id:UUID(uuidString:"ffffffff-ffff-4fff-8fff-ffffffffffff")!)
check(try history.latestPrintAttempt() == nil)
let diagnostics = JobJournal.PrintAttemptDiagnostics(operation:.submission,
    startedAt:Date(timeIntervalSince1970:0),endedAt:Date(timeIntervalSince1970:1),
    acknowledgedImageBytes:0,totalImageBytes:oldest.byteCount)
refuses { try history.savePrintAttemptDiagnostics(diagnostics,for:oldest.id) }
try stopBeforeSubmission(oldest,history)
try history.savePrintAttemptDiagnostics(diagnostics,for:oldest.id)
try history.discardDraft(oldest.id)
let next = try save(history,id:UUID(uuidString:"00000000-0000-4000-8000-000000000001")!)
let recent = try JobJournal(url:historyURL).latestPrintAttempt()!
check(recent.id == oldest.id && recent.status == .notSubmitted)
check(recent.report.contains("1970-01-01T00:00:01Z"))
_ = try history.authorizePrintOnce(next)
check(try history.latestPrintAttempt()?.id == next.id && history.latestPrintAttempt()?.status == .uncertain)
check(try history.printAttempt(oldest.id)?.report == recent.report)
check(try history.printAttempt(UUID()) == nil)

// Simulate an existing Build 2 database that predates the diagnostics table.
check(sqlite3_open(historyURL.path,&db) == SQLITE_OK)
check(sqlite3_exec(db,"DROP TABLE print_attempt_reports",nil,nil,nil) == SQLITE_OK)
sqlite3_close(db)
let migrated = try JobJournal(url:historyURL)
check(try migrated.latestPrintAttempt()?.id == next.id && migrated.latestPrintAttempt()?.status == .uncertain)
refuses { _ = try migrated.authorizePrintOnce(next) }

// A proved pre-submission stop can move the exact photo into a fresh review
// draft. Neither the old confirmation nor its report moves with the bytes.
let newDraftURL = root.appendingPathComponent("new-draft.sqlite")
let newDraftStore = try JobJournal(url:newDraftURL)
let discarded = try save(newDraftStore)
try newDraftStore.discardDraft(discarded.id)
let source = try save(newDraftStore), newID = UUID()
let freshPrinter = try verify(now:7)
refuses { _ = try newDraftStore.prepareNewAttempt(from:source.id,newID:newID,printer:freshPrinter,now:7) }
try stopBeforeSubmission(source,newDraftStore)
try newDraftStore.savePrintAttemptDiagnostics(diagnostics,for:source.id)
let sourceReport = try newDraftStore.latestPrintAttempt()!.report
refuses { _ = try newDraftStore.prepareNewAttempt(from:source.id,newID:source.id,printer:freshPrinter,now:7) }
refuses { _ = try newDraftStore.prepareNewAttempt(from:source.id,newID:discarded.id,printer:freshPrinter,now:7) }
refuses { _ = try newDraftStore.prepareNewAttempt(from:source.id,newID:newID,printer:freshPrinter,now:68) }
refuses { _ = try newDraftStore.prepareNewAttempt(from:source.id,newID:newID,printer:freshPrinter,now:6) }
let wrongDevice = try verify(SimulatedPrinter(deviceID:String(repeating:"08",count:16)))
refuses { _ = try newDraftStore.prepareNewAttempt(from:source.id,newID:newID,printer:wrongDevice,now:0) }
let changedFirmware = SimulatedPrinter()
changedFirmware.firmware = "TEST-FIRMWARE"
refuses { _ = try newDraftStore.prepareNewAttempt(from:source.id,newID:newID,printer:verify(changedFirmware),now:0) }

// Fail the replacement insert after retirement. A reopened connection still
// sees the old active bytes and report, with no partial replacement binding.
check(sqlite3_open(newDraftURL.path,&db) == SQLITE_OK)
check(sqlite3_exec(db,"CREATE TRIGGER fail_replacement BEFORE INSERT ON prepared_bindings BEGIN SELECT RAISE(IGNORE); END",nil,nil,nil) == SQLITE_OK)
refuses { _ = try newDraftStore.prepareNewAttempt(from:source.id,newID:newID,printer:freshPrinter,now:7) }
let rolledBack = try JobJournal(url:newDraftURL)
check(try rolledBack.activeBindings() == [source] && rolledBack.boundImage(source.id).jpeg == image.jpeg)
check(try rolledBack.binding(newID) == nil && rolledBack.latestPrintAttempt()?.report == sourceReport)
check(sqlite3_exec(db,"DROP TRIGGER fail_replacement",nil,nil,nil) == SQLITE_OK)
sqlite3_close(db)

let draft = try newDraftStore.prepareNewAttempt(from:source.id,newID:newID,printer:freshPrinter,now:7)
let reopenedDraft = try JobJournal(url:newDraftURL)
check(draft.id == newID && draft.checkedAt == freshPrinter.checkedAt && draft.id != source.id)
check(draft.device == source.device && draft.firmware == source.firmware && draft.settings == source.settings && draft.digest == source.digest)
check(try reopenedDraft.activeBindings() == [draft] && reopenedDraft.boundImage(draft.id).jpeg == image.jpeg)
check(try reopenedDraft.attemptState(draft.id) == nil && reopenedDraft.record(draft.id) == nil && reopenedDraft.unresolvedJobs().isEmpty)
check(try reopenedDraft.binding(source.id) == source && reopenedDraft.latestPrintAttempt()?.report == sourceReport)
refuses { _ = try reopenedDraft.boundImage(source.id) }
refuses { _ = try reopenedDraft.authorizePrintOnce(source) }
refuses { _ = try reopenedDraft.prepareNewAttempt(from:source.id,newID:UUID(),printer:freshPrinter,now:7) }
_ = try reopenedDraft.authorizePrintOnce(draft)
check(try reopenedDraft.attemptState(draft.id) == "reserved" && reopenedDraft.printAttempt(source.id)?.report == sourceReport)

let damagedURL = root.appendingPathComponent("damaged-source.sqlite"), damaged = try JobJournal(url:damagedURL)
let damagedSource = try save(damaged)
try stopBeforeSubmission(damagedSource,damaged)
check(sqlite3_open(damagedURL.path,&db) == SQLITE_OK)
check(sqlite3_exec(db,"UPDATE prepared_bindings SET jpeg=zeroblob(length(jpeg))",nil,nil,nil) == SQLITE_OK)
sqlite3_close(db)
let refusedID = UUID()
refuses { _ = try damaged.prepareNewAttempt(from:damagedSource.id,newID:refusedID,printer:freshPrinter,now:7) }
check(try damaged.activeBindings() == [damagedSource] && damaged.binding(refusedID) == nil)

let draftRaceURL = root.appendingPathComponent("race-new-draft.sqlite"), draftRace = try JobJournal(url:draftRaceURL)
let draftRaceSource = try save(draftRace,id:fixedID)
try stopBeforeSubmission(draftRaceSource,draftRace)
let left = try child("race-new-draft",draftRaceURL), right = try child("race-new-draft",draftRaceURL)
left.waitUntilExit(); right.waitUntilExit()
check([left.terminationStatus,right.terminationStatus].sorted() == [0,2])
let winningDrafts = try draftRace.activeBindings()
check(winningDrafts.count == 1 && winningDrafts.first?.id != draftRaceSource.id)
check(try draftRace.latestPrintAttempt()?.id == draftRaceSource.id && draftRace.attemptState(winningDrafts[0].id) == nil)

// Read-only recovery can prove completion while the original permit remains
// uncertain. Its optional diagnostics leave the original transfer intact.
let recoveryURL = root.appendingPathComponent("reconciled-history.sqlite")
let recoveryStore = try JobJournal(url:recoveryURL), recoveryBinding = try save(recoveryStore)
let recoveryClock = Time(), recoveryPeer = SimulatedPrinter()
let (originalPump,_) = try authorized(recoveryBinding,recoveryStore,recoveryClock)
let originalDriver = AccessoryStreamDriver(pump:originalPump,io:IO(recoveryPeer),clock:{ recoveryClock.now },update:{ _ in })
originalDriver.start()
for _ in 0..<10000 {
    recoveryClock.now += 0.001; originalDriver.tick()
    if try recoveryStore.record(recoveryBinding.id)?.seenPrinting == true {
        originalDriver.cancel("Test interruption after printer observed in progress")
        break
    }
}
check(try recoveryStore.attemptState(recoveryBinding.id) == "uncertain")
let transfer = JobJournal.PrintAttemptDiagnostics(operation:.submission,
    startedAt:Date(timeIntervalSince1970:2),endedAt:Date(timeIntervalSince1970:3),
    acknowledgedImageBytes:originalPump.acknowledgedImageBytes,totalImageBytes:originalPump.totalImageBytes,
    gatt:.init(txQueuedBytes:65000,txAcknowledgedBytes:64999,writeCallbacks:51,rxBytes:381,protocolMTU:514,acknowledgementPeriod:0),
    failureStage:.exchange)
try recoveryStore.savePrintAttemptDiagnostics(transfer,for:recoveryBinding.id)
let reconcile = try SubmissionCoordinator(recover:recoveryBinding.id,journal:recoveryStore,now:recoveryClock.now,pollInterval:0.01)
let recoveryPump = AccessoryStreamPump(coordinator:reconcile,now:recoveryClock.now)
let recoveryDriver = AccessoryStreamDriver(pump:recoveryPump,io:IO(recoveryPeer),clock:{ recoveryClock.now },update:{ _ in })
let mutations = recoveryPeer.mutationCount
drive(recoveryDriver,recoveryClock)
check(recoveryPeer.mutationCount == mutations && recoveryPump.succeeded)
check(try recoveryStore.attemptState(recoveryBinding.id) == "uncertain")
let beforeReport = try JobJournal(url:recoveryURL).latestPrintAttempt()!
check(beforeReport.status == .completed && beforeReport.report.contains("TX queued 65000"))
check(beforeReport.report.contains("Printed-page counter · 13 → 14"))
check(beforeReport.report.contains("Calibration counter · 2 → 2"))
let readback = JobJournal.PrintAttemptDiagnostics(operation:.recovery,
    startedAt:Date(timeIntervalSince1970:4),endedAt:Date(timeIntervalSince1970:5),
    acknowledgedImageBytes:0,totalImageBytes:0)
try recoveryStore.savePrintAttemptDiagnostics(readback,for:recoveryBinding.id)
let completed = try JobJournal(url:recoveryURL).latestPrintAttempt()!
check(completed.status == .completed && completed.report.contains("TX queued 65000") && completed.report.contains("Read-only recovery"))
for sensitive in [recoveryBinding.id.uuidString,recoveryBinding.device,recoveryBinding.digest,recoveryBinding.firmware] {
    check(!completed.report.contains(sensitive))
}
refuses { _ = try recoveryStore.authorizePrintOnce(recoveryBinding) }

// Diagnostics are optional. Malformed stored telemetry cannot override the
// verified job state or become arbitrary exported text.
check(sqlite3_open(recoveryURL.path,&db) == SQLITE_OK)
check(sqlite3_exec(db,"UPDATE print_attempt_reports SET report='malformed telemetry' WHERE operation='recovery'",nil,nil,nil) == SQLITE_OK)
sqlite3_close(db)
let withoutRecoveryReport = try JobJournal(url:recoveryURL).latestPrintAttempt()!
check(withoutRecoveryReport.status == .completed)
check(withoutRecoveryReport.report.contains("TX queued 65000") && !withoutRecoveryReport.report.contains("malformed telemetry"))

print("Single-job authorization passed: complete framed streams, exact JPEG/one copy, empty final, lost replies, every first-mutation prefix, cancellation, read-only recovery and no replay")
print("Durable permission passed: review matching, storage failure, one-use tokens, 5 abrupt process exits, restart refusal and competing confirmations")
print("Print history passed: completed and uncertain process exits, discarded drafts, legacy database, report privacy and read-only reconciliation")
print("Fresh drafts passed: proved pre-submission stop, exact bytes/settings, rollback, restart, history and competing processes")
