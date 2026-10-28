import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
import SQLite3

func check(_ value: Bool, file: StaticString = #file, line: UInt = #line) { precondition(value, file:file, line:line) }
func refuses(_ body: () throws -> Void) { do { try body(); fatalError("Expected refusal") } catch {} }
func jpeg(_ level: CGFloat = 0.5) -> Data {
    let context = CGContext(data:nil,width:768,height:1152,bitsPerComponent:8,bytesPerRow:0,space:CGColorSpace(name:CGColorSpace.sRGB)!,bitmapInfo:CGImageAlphaInfo.noneSkipLast.rawValue)!
    context.setFillColor(CGColor(gray:level,alpha:1)); context.fill(CGRect(x:0,y:0,width:768,height:1152))
    let data = NSMutableData(), dest = CGImageDestinationCreateWithData(data,UTType.jpeg.identifier as CFString,1,nil)!
    CGImageDestinationAddImage(dest,context.makeImage()!,[kCGImageDestinationLossyCompressionQuality:1] as CFDictionary)
    precondition(CGImageDestinationFinalize(dest)); return data as Data
}
final class Time { var now: TimeInterval = 100 }
final class IO: AccessoryDuplex {
    let peer: SimulatedPrinter
    var openCount = 0, closeCount = 0, total = 0, readTotal = 0
    var writeLimit = 13, readLimit = 37, failAt: Int?, readFailAt: Int?
    var blocked = false, noOpen = false, closed = false
    var handler: ((AccessoryIOEvent) -> Void)?
    init(_ peer: SimulatedPrinter = SimulatedPrinter()) { self.peer = peer }
    var hasBytes: Bool { !closed && !peer.output.isEmpty }
    var hasSpace: Bool { !closed }
    func open(_ handler: @escaping (AccessoryIOEvent) -> Void) {
        openCount += 1; self.handler = handler
        if !noOpen { handler(.opened(.input)); handler(.opened(.output)) }
    }
    func read(maximum: Int) -> AccessoryRead {
        if let cut = readFailAt, readTotal >= cut { return .failed }
        guard hasBytes else { return .wouldBlock }
        let count = min(maximum,readLimit,peer.output.count,readFailAt.map { $0-readTotal } ?? Int.max)
        let bytes = Array(peer.output.prefix(count)); peer.output.removeFirst(count); readTotal += count
        return .bytes(bytes)
    }
    func write(_ bytes: [UInt8]) -> Int {
        if let failAt, total >= failAt { return -1 }
        if blocked { return 0 }
        let count = peer.write(bytes,limit:min(writeLimit,failAt.map { $0-total } ?? Int.max)); total += count; return count
    }
    func close() { closeCount += 1; closed = true }
}
func run(_ driver: AccessoryStreamDriver, _ time: Time, count: Int = 100000) {
    driver.start()
    for _ in 0..<count { if driver.closed { return }; time.now += 0.01; driver.tick() }
    fatalError("Driver did not terminate")
}
func preflight(_ peer: SimulatedPrinter = SimulatedPrinter(), id: String? = nil) throws -> (AccessoryStreamPump,IO,Time) {
    let time = Time(), io = IO(peer)
    let pump = try AccessoryStreamPump(expectedDeviceID:id,expectedFirmware:"G1L1FA2105AR",now:time.now)
    let driver = AccessoryStreamDriver(pump:pump,io:io,clock:{ time.now },update:{ _ in })
    run(driver,time); return (pump,io,time)
}
let settings = JobBinding.Settings(layout:"Preserve edges",quality:100)
let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
defer { try? FileManager.default.removeItem(at:root) }
let image = try PreparedJobImage(jpeg:jpeg())
let id = UUID(uuidString:"11111111-1111-4111-8111-111111111111")!

if CommandLine.arguments.count > 2 {
    let mode = CommandLine.arguments[1], url = URL(fileURLWithPath:CommandLine.arguments[2])
    let (pump,_,time) = try preflight(), store = try JobJournal(url:url)
    let chosen = mode == "race" ? UUID() : id
    do {
        _ = try store.bind(id:chosen,image:image,settings:settings,printer:pump.verified!,now:time.now)
        if mode == "pending" {
            let coordinator = try SubmissionCoordinator(boundJob:chosen,journal:store,now:time.now,pollInterval:0)
            let peer = SimulatedPrinter()
            for _ in 0..<10000 {
                time.now += 0.01; coordinator.write(now:time.now) { bytes in
                    if (try? store.record(chosen))?.pendingOpcode != nil { return 0 }
                    return peer.write(bytes)
                }
                peer.deliver(to:coordinator,now:time.now)
                if (try store.record(chosen))?.pendingOpcode != nil { _exit(0) }
            }
            fatalError("No pending request")
        }
        _exit(0) // process death without destructors/SQLite close
    } catch { if mode == "race" { _exit(2) }; throw error }
}

let (success,io,time) = try preflight()
check(success.succeeded && success.verified != nil && io.openCount == 1 && io.closeCount == 1 && io.peer.mutationCount == 0)
check(success.acceptedBytes == io.total && success.receivedBytes == io.readTotal)
let tx = io.total, rx = io.readTotal
for limit in [1,2,7,4096] {
    let t = Time(), fake = IO(); fake.writeLimit = limit; fake.readLimit = limit
    let pump = try AccessoryStreamPump(expectedFirmware:"G1L1FA2105AR",now:t.now)
    let driver = AccessoryStreamDriver(pump:pump,io:fake,clock:{ t.now },update:{ _ in })
    run(driver,t); check(pump.succeeded && fake.closeCount == 1 && fake.peer.mutationCount == 0)
}
for cut in 0..<tx {
    let t = Time(), fake = IO(); fake.failAt = cut; fake.writeLimit = 1
    let pump = try AccessoryStreamPump(expectedFirmware:"G1L1FA2105AR",now:t.now)
    let driver = AccessoryStreamDriver(pump:pump,io:fake,clock:{ t.now },update:{ _ in })
    run(driver,t); let before = fake.total
    driver.tick(); driver.cancel("Again"); fake.handler?(.readable)
    check(driver.closed && !pump.succeeded && pump.verified == nil && fake.closeCount == 1 && fake.total == before && before == cut && fake.peer.mutationCount == 0)
}
for cut in 0..<rx {
    let t = Time(), fake = IO(); fake.readFailAt = cut; fake.readLimit = 1
    let pump = try AccessoryStreamPump(expectedFirmware:"G1L1FA2105AR",now:t.now)
    let driver = AccessoryStreamDriver(pump:pump,io:fake,clock:{ t.now },update:{ _ in })
    run(driver,t); check(!pump.succeeded && pump.verified == nil && fake.closeCount == 1)
}
for fault in ["no-open","backpressure","disconnect","cancel","clock","malformed"] {
    let t = Time(), fake = IO(); fake.noOpen = fault == "no-open"; fake.blocked = fault == "backpressure"
    let pump = try AccessoryStreamPump(expectedFirmware:"G1L1FA2105AR",now:t.now)
    let driver = AccessoryStreamDriver(pump:pump,io:fake,clock:{ t.now },update:{ _ in })
    driver.start()
    switch fault {
    case "disconnect": fake.handler?(.ended)
    case "cancel": driver.cancel("Host inactive")
    case "clock": t.now -= 1
    case "malformed": fake.peer.output = [0,0,0,1,1,9]
    default: break
    }
    run(driver,t); check(!pump.succeeded && fake.closeCount == 1 && fake.peer.mutationCount == 0)
}
// Releasing the stream owner terminates its pump and closes once.
let releasedTime = Time(), releasedIO = IO(); releasedIO.blocked = true
let releasedPump = try AccessoryStreamPump(expectedFirmware:"G1L1FA2105AR",now:releasedTime.now)
var released: AccessoryStreamDriver? = AccessoryStreamDriver(pump:releasedPump,io:releasedIO,clock:{ releasedTime.now },update:{ _ in })
released?.start(); released = nil
check(releasedPump.terminal && !releasedPump.succeeded && releasedIO.closeCount == 1)
let wrong = try preflight(id:String(repeating:"08",count:16)); check(!wrong.0.succeeded && wrong.0.verified == nil)
let fw = SimulatedPrinter(); fw.firmware = "OTHER"; check(try !preflight(fw).0.succeeded)
for op: UInt8 in [12,14,48,24,10,28,6] {
    for payload in [[op], [op,0,0,0,0,0]] {
        var gate = ReadOnlyFrameGate(), bytes = 0
        refuses { _ = try gate.write(SimulatedPrinter.frame(payload)) { bytes += $0.count; return $0.count } }
        check(bytes == 0)
    }
}
var gate = ReadOnlyFrameGate(), nativeCalls = 0
let first = SimulatedPrinter.frame([4,1])
_ = try gate.write(first) { _ in nativeCalls += 1; return 1 }
refuses { _ = try gate.write(Array(first.dropFirst()) + [0]) { _ in nativeCalls += 1; return 1 } }
check(nativeCalls == 1)

let url = root.appendingPathComponent("bound.sqlite"), store = try JobJournal(url:url)
let bound = try store.bind(id:id,image:image,settings:settings,printer:success.verified!,now:time.now)
check(try store.bind(id:id,image:image,settings:settings,printer:success.verified!,now:time.now) == bound)
let reopened = try JobJournal(url:url)
check(try reopened.activeBindings() == [bound]); check(try reopened.boundImage(id).jpeg == image.jpeg)
refuses { _ = try store.bind(id:UUID(),image:image,settings:settings,printer:success.verified!,now:time.now) }
refuses { _ = try store.bind(id:id,image:PreparedJobImage(jpeg:jpeg(0.7)),settings:settings,printer:success.verified!,now:time.now) }
refuses { _ = try store.bind(id:id,image:image,settings:.init(layout:"Fit",quality:95),printer:success.verified!,now:time.now) }
refuses { _ = try store.bind(id:UUID(),image:image,settings:settings,printer:success.verified!,now:time.now+61) }
let changed = try SubmissionCoordinator(boundJob:id,journal:store,now:time.now,pollInterval:0), peer = SimulatedPrinter()
peer.firmware = "CHANGED"
for step in 1..<1000 {
    let now = time.now + Double(step)*0.01; changed.write(now:now) { peer.write($0) }; peer.deliver(to:changed,now:now)
    if changed.terminal { break }
}
let changedRecord = try store.record(id)
check(changed.state == .notSubmitted && peer.startCount == 0 && changedRecord == nil)
// Even an accidental submission coordinator cannot cross the live frame guard.
let attempt = try SubmissionCoordinator(boundJob:id,journal:store,now:time.now,pollInterval:0)
let guarded = AccessoryStreamPump(coordinator:attempt,now:time.now), fake = IO(), guardedTime = Time(); guardedTime.now = time.now
let driver = AccessoryStreamDriver(pump:guarded,io:fake,clock:{ guardedTime.now },update:{ _ in })
run(driver,guardedTime)
check(!guarded.succeeded && guarded.result.contains("policy blocked") && fake.peer.startCount == 0 && fake.peer.mutationCount == 0 && fake.closeCount == 1)
check(try store.record(id)?.pendingOpcode == 12)
refuses { try store.discardDraft(id) }; refuses { _ = try SubmissionCoordinator(boundJob:id,journal:store,now:guardedTime.now) }
refuses { _ = try store.bind(id:UUID(),image:image,settings:settings,printer:success.verified!,now:time.now) }
// Saved-byte submission succeeds only against an explicitly supplied memory peer.
let offlineStore = try JobJournal(url:root.appendingPathComponent("offline-bound.sqlite"))
_ = try offlineStore.bind(id:id,image:image,settings:settings,printer:success.verified!,now:time.now)
let offline = try SubmissionCoordinator(boundJob:id,journal:offlineStore,now:time.now,pollInterval:0), offlinePeer = SimulatedPrinter()
for step in 1..<10000 {
    let now = time.now + Double(step)*0.01
    offline.write(now:now) { offlinePeer.write($0) }; offlinePeer.deliver(to:offline,now:now)
    if offline.terminal { break }
}
check(offline.state == .completed && offlinePeer.startCount == 1 && Data(offlinePeer.uploadedData) == image.jpeg)
check(try offlineStore.activeBindings().isEmpty)
refuses { try offlineStore.discardDraft(id) }
refuses { _ = try SubmissionCoordinator(boundJob:id,journal:offlineStore,now:time.now) }
_ = try offlineStore.bind(id:UUID(),image:image,settings:settings,printer:success.verified!,now:time.now)
// Discard is available only for a draft that has no possible submission.
let draftStore = try JobJournal(url:root.appendingPathComponent("discard.sqlite"))
_ = try draftStore.bind(id:id,image:image,settings:settings,printer:success.verified!,now:time.now)
try draftStore.discardDraft(id); check(try draftStore.activeBindings().isEmpty)
refuses { _ = try draftStore.boundImage(id) }; refuses { _ = try draftStore.bind(id:id,image:image,settings:settings,printer:success.verified!,now:time.now) }
_ = try draftStore.bind(id:UUID(),image:image,settings:settings,printer:success.verified!,now:time.now)
// Corrupted saved data cannot be reconstructed into a job.
let corruptURL = root.appendingPathComponent("corrupt.sqlite"), corrupt = try JobJournal(url:corruptURL)
_ = try corrupt.bind(id:id,image:image,settings:settings,printer:success.verified!,now:time.now)
var db: OpaquePointer?; check(sqlite3_open(corruptURL.path,&db) == SQLITE_OK)
check(sqlite3_exec(db,"UPDATE prepared_bindings SET jpeg=zeroblob(length(jpeg))",nil,nil,nil) == SQLITE_OK); sqlite3_close(db)
refuses { _ = try corrupt.boundImage(id) }; refuses { _ = try SubmissionCoordinator(boundJob:id,journal:corrupt,now:time.now) }
func child(_ mode: String, _ url: URL) throws -> Process {
    let p = Process(); p.executableURL = URL(fileURLWithPath:CommandLine.arguments[0]); p.arguments = [mode,url.path]; try p.run(); return p
}
for mode in ["saved","pending"] {
    let path = root.appendingPathComponent("\(mode).sqlite"), p = try child(mode,path); p.waitUntilExit(); check(p.terminationStatus == 0)
    let after = try JobJournal(url:path)
    check(try after.activeBindings().first?.id == id); check(try after.boundImage(id).jpeg == image.jpeg)
    if mode == "pending" {
        refuses { _ = try SubmissionCoordinator(boundJob:id,journal:after,now:time.now) }
        refuses { try after.discardDraft(id) }
    } else { check(try after.record(id) == nil) }
    refuses { _ = try after.bind(id:UUID(),image:image,settings:settings,printer:success.verified!,now:time.now) }
}
let raceURL = root.appendingPathComponent("race.sqlite"); _ = try JobJournal(url:raceURL)
let p1 = try child("race",raceURL), p2 = try child("race",raceURL); p1.waitUntilExit(); p2.waitUntilExit()
check([p1.terminationStatus,p2.terminationStatus].sorted() == [0,2]); check(try JobJournal(url:raceURL).activeBindings().count == 1)
print("Accessory adapter passed: full preflight, \(tx) write and \(rx) read interruption offsets, fragmentation, backpressure, lifecycle/deadline failures, close-once and zero print bytes")
print("Durable bindings passed: exact bytes/identity/settings, reopen, stale/mismatched refusal, output policy, corrupt image, discard tombstones, process death and competing reservations")
