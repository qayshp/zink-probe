import Foundation
import ImageIO
import CoreGraphics
import UniformTypeIdentifiers
import SQLite3
import Darwin

func refused(_ block: () throws -> Void) { do { try block(); fatalError("Expected refusal") } catch {} }
let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
defer { try? FileManager.default.removeItem(at:root) }
func makeJPEG() -> Data {
    let context = CGContext(data:nil,width:768,height:1152,bitsPerComponent:8,bytesPerRow:0,space:CGColorSpace(name:CGColorSpace.sRGB)!,bitmapInfo:CGImageAlphaInfo.noneSkipLast.rawValue)!
    context.setFillColor(CGColor(gray:0.5,alpha:1)); context.fill(CGRect(x:0,y:0,width:768,height:1152))
    let output = NSMutableData(), image = context.makeImage()!
    let destination = CGImageDestinationCreateWithData(output,UTType.jpeg.identifier as CFString,1,nil)!
    CGImageDestinationAddImage(destination,image,[kCGImageDestinationLossyCompressionQuality:1] as CFDictionary)
    precondition(CGImageDestinationFinalize(destination)); return output as Data
}
let jpeg = makeJPEG(), image = try PreparedJobImage(jpeg:jpeg)
assert(image.sampling == "4:4:4")
refused { _ = try PreparedJobImage(jpeg:Data([255,216,255,217])) }
for count in [0,10,jpeg.count/2,jpeg.count-2] { refused { _ = try PreparedJobImage(jpeg:jpeg.prefix(count)) } }
func drive(_ c: SubmissionCoordinator, _ p: SimulatedPrinter, start: Double = 0, steps: Int = 30000, writeLimit: Int = 13, readLimit: Int = 37) -> Double {
    var now = start
    for i in 0..<steps {
        if c.terminal { return now }
        now += 0.001
        if i%7 == 0 { c.write(now:now) { _ in 0 } } // backpressure
        c.write(now:now) { p.write($0,limit:writeLimit) }
        p.deliver(to:c,now:now,limit:readLimit)
        c.tick(now:now)
    }
    return now
}
func fresh(_ journal: JobJournal, _ p: SimulatedPrinter, _ id: UUID = UUID(), timeout: Double = 100) throws -> SubmissionCoordinator {
    try SubmissionCoordinator(image:image,id:id,expectedDeviceID:p.device,journal:journal,now:0,timeout:timeout,pollInterval:0)
}
// Actual process death leaves only committed journal evidence, never a resumable plan.
let arguments = CommandLine.arguments
let crashID = UUID(uuidString:"00000000-0000-0000-0000-000000000111")!
if arguments.count == 4 && arguments[1] == "--crash" {
    let journal = try JobJournal(url:URL(fileURLWithPath:arguments[2])), peer = SimulatedPrinter()
    let c = try fresh(journal,peer,crashID)
    var now = 0.0
    while !c.terminal {
        now += 0.001; c.write(now:now) { peer.write($0) }
        if arguments[3] == "pending" && peer.startCount == 1 { _exit(0) }
        peer.deliver(to:c,now:now)
        if arguments[3] == "uploaded" && c.state == .observing { _exit(0) }
        if arguments[3] == "printing" {
            let record = try journal.record(crashID)
            if record?.seenPrinting == true { _exit(0) }
        }
    }
    fatalError("Crash boundary not reached")
}
// Successful uploads, one-byte stream fragments, optional empty final, durable history.
for empty in [false,true] {
    let url = root.appendingPathComponent("success-\(empty).sqlite"), id = UUID()
    let journal = try JobJournal(url:url), peer = SimulatedPrinter(); peer.requireEmptyFinal = empty
    let coordinator = try fresh(journal,peer,id)
    _ = drive(coordinator,peer,writeLimit:empty ? 1 : 13,readLimit:empty ? 1 : 37)
    assert(coordinator.state == .completed && !coordinator.physicalEjectionConfirmed)
    assert(peer.startCount == 1 && peer.received == jpeg.count && peer.uploadedData == Array(jpeg))
    let saved = try journal.record(id)!
    assert(saved.state == "completed" && saved.uploadAcknowledged == true && saved.seenPrinting == true)
    refused { _ = try fresh(journal,peer,id) } // completed local ID is permanently spent
    let second = try fresh(journal,peer) // verified completion frees device for a distinct job
    _ = drive(second,peer); assert(second.state == .completed && peer.startCount == 2)
}
// Wrong identity and paused printer never create a print job or claim.
for mismatch in [false,true] {
    let journal = try JobJournal(url:root.appendingPathComponent("preflight-\(mismatch).sqlite")), peer = SimulatedPrinter()
    peer.mismatchIdentity = mismatch; peer.paused = !mismatch
    let c = try fresh(journal,peer); _ = drive(c,peer)
    assert(c.state == .notSubmitted && peer.mutationCount == 0)
    let unresolved = try journal.unresolvedJobs(); assert(unresolved.isEmpty)
}
// Every lost mutation reply is uncertain, never retried, and blocks a new ID.
for opcode: UInt8 in [12,48,14] {
    let journal = try JobJournal(url:root.appendingPathComponent("lost-\(opcode).sqlite")), peer = SimulatedPrinter()
    peer.droppedOpcode = opcode
    let id = UUID(), c = try fresh(journal,peer,id)
    _ = drive(c,peer,steps:20000)
    assert(c.state == .uncertain && peer.startCount == 1)
    assert(peer.requests.filter { $0[0] == opcode }.count == 1)
    refused { _ = try fresh(journal,peer,UUID()) }
    let mutations = peer.mutationCount
    if opcode != 12 {
        peer.droppedOpcode = nil; peer.output = []; peer.input = []
        let recovery = try SubmissionCoordinator(recover:id,journal:journal,now:0,timeout:1,pollInterval:0)
        _ = drive(recovery,peer,steps:2000)
        assert(recovery.state == .uncertain && peer.mutationCount == mutations)
    } else { refused { _ = try SubmissionCoordinator(recover:id,journal:journal,now:0) } }
}
// False completion: missing processing evidence, foreign job, extra page, changed calibration.
for fault in 0..<5 {
    let journal = try JobJournal(url:root.appendingPathComponent("fault-\(fault).sqlite")), peer = SimulatedPrinter()
    peer.neverPrint = fault == 0; peer.foreignJob = fault == 1; peer.extraPage = fault == 2
    peer.changedCalibration = fault == 3; peer.badFinalOffset = fault == 4
    let c = try fresh(journal,peer,timeout:2); _ = drive(c,peer,steps:4000)
    assert(c.state == .uncertain && peer.startCount == 1)
    refused { _ = try fresh(journal,peer) }
}
// Stop after each request boundary, including all upload chunks and observations.
let sample = SimulatedPrinter(), sampleJournal = try JobJournal(url:root.appendingPathComponent("count.sqlite"))
let sampleJob = try fresh(sampleJournal,sample); _ = drive(sampleJob,sample)
for boundary in 0..<sample.requests.count {
    let url = root.appendingPathComponent("cancel-\(boundary).sqlite"), journal = try JobJournal(url:url), peer = SimulatedPrinter(), id = UUID()
    let c = try fresh(journal,peer,id)
    var now = 0.0
    while !c.terminal && peer.requests.count < boundary {
        now += 0.001; c.write(now:now) { peer.write($0) }; peer.deliver(to:c,now:now)
    }
    let before = peer.mutationCount
    c.cancel(); c.disconnected(); c.write(now:now+1) { peer.write($0) }
    assert(peer.mutationCount == before && c.state != .completed)
    if try journal.record(id) != nil {
        let reopened = try JobJournal(url:url)
        refused { _ = try fresh(reopened,peer) }
    } else { assert(c.state == .notSubmitted && before == 0) }
}
print("Coordinator passed: real JPEG, full framed jobs, completion, lost replies, false-success guards, cancellation boundaries and duplicate prevention")

for point in ["pending","uploaded","printing"] {
    let url = root.appendingPathComponent("death-\(point).sqlite")
    let child = Process(); child.executableURL = URL(fileURLWithPath:arguments[0])
    child.arguments = ["--crash",url.path,point]
    try child.run(); child.waitUntilExit(); assert(child.terminationStatus == 0)
    let journal = try JobJournal(url:url), peer = SimulatedPrinter()
    refused { _ = try fresh(journal,peer,crashID) }; refused { _ = try fresh(journal,peer) }
    if point == "pending" {
        refused { _ = try SubmissionCoordinator(recover:crashID,journal:journal,now:0) }
    } else {
        peer.job = 17; peer.uploaded = true
        let c = try SubmissionCoordinator(recover:crashID,journal:journal,now:0,pollInterval:0)
        _ = drive(c,peer)
        assert(c.state == .completed && peer.mutationCount == 0)
        refused { _ = try fresh(journal,peer,crashID) }
    }
}
// A storage failure after preflight must not return any mutating bytes.
let failedURL = root.appendingPathComponent("storage.sqlite"), failedJournal = try JobJournal(url:failedURL)
var db: OpaquePointer?; assert(sqlite3_open(failedURL.path,&db) == SQLITE_OK)
assert(sqlite3_exec(db,"CREATE TRIGGER fail_update BEFORE UPDATE ON jobs BEGIN SELECT RAISE(FAIL,'injected'); END",nil,nil,nil) == SQLITE_OK)
sqlite3_close(db)
let failedPeer = SimulatedPrinter(), failedJob = try fresh(failedJournal,failedPeer)
_ = drive(failedJob,failedPeer); assert(failedJob.state == .uncertain && failedPeer.mutationCount == 0)
refused { _ = try fresh(failedJournal,failedPeer) }
// Existing three-column journals migrate without losing their device claim.
let migrationURL = root.appendingPathComponent("legacy.sqlite")
var legacy: OpaquePointer?; assert(sqlite3_open(migrationURL.path,&legacy) == SQLITE_OK)
assert(sqlite3_exec(legacy,"CREATE TABLE jobs(id TEXT PRIMARY KEY,device TEXT NOT NULL UNIQUE,record TEXT NOT NULL)",nil,nil,nil) == SQLITE_OK)
let sourceRecord = try failedJournal.unresolvedJobs()[0]
let encoded = String(decoding:try JSONEncoder().encode(sourceRecord),as:UTF8.self).replacingOccurrences(of:"'",with:"''")
let insert = "INSERT INTO jobs VALUES('\(sourceRecord.id.uuidString)','\(sourceRecord.device)','\(encoded)')"
assert(sqlite3_exec(legacy,insert,nil,nil,nil) == SQLITE_OK); sqlite3_close(legacy)
let migrated = try JobJournal(url:migrationURL)
let restored = try migrated.record(sourceRecord.id)!
assert(restored.digest == sourceRecord.digest)
refused { _ = try fresh(migrated,SimulatedPrinter()) }
print("Coordinator process-death recovery, write-failure gating and legacy migration passed")

// Final write can be processed by the peer even though the final ACK is lost.
let finalJournal = try JobJournal(url:root.appendingPathComponent("lost-final.sqlite")), finalPeer = SimulatedPrinter(), finalID = UUID()
finalPeer.dropFinalAck = true
let finalJob = try fresh(finalJournal,finalPeer,finalID)
_ = drive(finalJob,finalPeer,steps:20000)
assert(finalPeer.uploaded && finalJob.state == .uncertain)
let finalRecord = try finalJournal.record(finalID)!
assert(finalRecord.uploadAcknowledged != true && finalRecord.pendingOpcode == 14)
let finalMutations = finalPeer.mutationCount
let finalRecovery = try SubmissionCoordinator(recover:finalID,journal:finalJournal,now:0,timeout:1,pollInterval:0)
_ = drive(finalRecovery,finalPeer,steps:2000)
assert(finalRecovery.state == .uncertain && finalPeer.mutationCount == finalMutations)
refused { _ = try fresh(finalJournal,finalPeer) }
// Interrupt at every byte offset of the first mutation's HP+ frame.
for offset in 0...11 {
    let journal = try JobJournal(url:root.appendingPathComponent("partial-\(offset).sqlite")), peer = SimulatedPrinter()
    let c = try fresh(journal,peer); var now = 0.0
    while c.state == .preflight {
        now += 0.001; c.write(now:now) { peer.write($0) }; peer.deliver(to:c,now:now)
    }
    assert(c.state == .uploading)
    var written = 0
    while written < offset {
        now += 0.001
        c.write(now:now) { bytes in let n = peer.write(bytes,limit:offset-written); written += n; return n }
    }
    if offset == 0 { c.write(now:now) { _ in 0 } }
    c.disconnected(); let count = peer.mutationCount
    c.write(now:now+1) { peer.write($0) }; assert(peer.mutationCount == count)
    refused { _ = try fresh(journal,peer) }
}
let clockJournal = try JobJournal(url:root.appendingPathComponent("clock-invalid.sqlite")), clockPeer = SimulatedPrinter()
clockPeer.initialFlags = 1
let blockedClock = try fresh(clockJournal,clockPeer); _ = drive(blockedClock,clockPeer)
assert(blockedClock.state == .notSubmitted && clockPeer.mutationCount == 0)
print("Final-ACK loss, every first-mutation byte offset and clock-invalid gating passed")
// Two coordinators can preflight concurrently, but only one may claim the device.
let raceJournalURL = root.appendingPathComponent("coordinator-race.sqlite")
let firstStore = try JobJournal(url:raceJournalURL), secondStore = try JobJournal(url:raceJournalURL)
let firstPeer = SimulatedPrinter(), secondPeer = SimulatedPrinter()
let firstJob = try fresh(firstStore,firstPeer), secondJob = try fresh(secondStore,secondPeer)
var raceTime = 0.0
while firstJob.state == .preflight {
    raceTime += 0.001; firstJob.write(now:raceTime) { firstPeer.write($0) }; firstPeer.deliver(to:firstJob,now:raceTime)
}
_ = drive(secondJob,secondPeer)
assert(secondJob.state == .notSubmitted && secondPeer.mutationCount == 0)
_ = drive(firstJob,firstPeer,start:raceTime)
assert(firstJob.state == .completed && firstPeer.startCount == 1)
print("Competing coordinators: one claim, one simulated PrintStart")
// Header/metadata checks catch wrong dimensions, progressive mode and EXIF rotation.
var header = Array(jpeg)
let sof = (0..<header.count-1).first { header[$0] == 255 && header[$0+1] == 192 }!
var progressive = header; progressive[sof+1] = 194
refused { _ = try PreparedJobImage(jpeg:Data(progressive)) }
var dimension = header; dimension[sof+8] = 1
refused { _ = try PreparedJobImage(jpeg:Data(dimension)) }
let rotationData = NSMutableData()
let imageSource = CGImageSourceCreateWithData(jpeg as CFData,nil)!
let rotated = CGImageDestinationCreateWithData(rotationData,UTType.jpeg.identifier as CFString,1,nil)!
CGImageDestinationAddImageFromSource(rotated,imageSource,0,[kCGImagePropertyOrientation:6] as CFDictionary)
assert(CGImageDestinationFinalize(rotated))
refused { _ = try PreparedJobImage(jpeg:rotationData as Data) }
// A contradiction remains blocking even if the next recovery would look normal.
let blockedJournal = try JobJournal(url:root.appendingPathComponent("attribution.sqlite")), blockedPeer = SimulatedPrinter(), blockedID = UUID()
blockedPeer.foreignJob = true
let blockedJob = try fresh(blockedJournal,blockedPeer,blockedID); _ = drive(blockedJob,blockedPeer)
let blockedRecord = try blockedJournal.record(blockedID)!
assert(blockedRecord.attributionBlocked == true)
refused { _ = try SubmissionCoordinator(recover:blockedID,journal:blockedJournal,now:0) }
// Recovery rechecks the saved physical identity and firmware before attributing completion.
let firmwareURL = root.appendingPathComponent("firmware-change.sqlite"), firmwareStore = try JobJournal(url:firmwareURL)
let fwPeer = SimulatedPrinter(), fwID = UUID(), fwJob = try fresh(firmwareStore,fwPeer,fwID)
var fwTime = 0.0
while fwJob.state != .observing {
    fwTime += 0.001; fwJob.write(now:fwTime) { fwPeer.write($0) }; fwPeer.deliver(to:fwJob,now:fwTime)
}
fwJob.disconnected(); fwPeer.firmware = "G1L1FA2105AX"
let fwMutations = fwPeer.mutationCount
let fwRecovery = try SubmissionCoordinator(recover:fwID,journal:firmwareStore,now:0,pollInterval:0)
_ = drive(fwRecovery,fwPeer)
assert(fwRecovery.state == .uncertain && fwPeer.mutationCount == fwMutations)
print("Image header/orientation validation and sticky attribution/firmware guards passed")
