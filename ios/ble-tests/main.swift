import Foundation

var checks = 0
func expect(_ condition: Bool, _ label: String) {
    checks += 1
    if !condition { fatalError("BLE test failed: \(label)") }
}
func rejects(_ label: String, _ operation: () throws -> Void) {
    checks += 1
    do { try operation(); fatalError("BLE test should reject: \(label)") }
    catch { }
}
func le(_ n: Int, _ width: Int) -> [UInt8] { (0..<width).map { UInt8((n >> (8*$0)) & 255) } }
func tlv(_ tag: UInt8, _ data: [UInt8]) -> [UInt8] { [tag] + le(data.count,2) + data }
let table = tlv(1,[9,0]) + tlv(2,[1,0]) + tlv(3,[5,4,8,12,14,48]) + tlv(7,[1,1]) + tlv(11,[2,1,2])
let firmware: [UInt8] = [5,1,12] + Array("G1L1FA2105AR".utf8)
let status: [UInt8] = [9,1,0,0,0,0,2,1,3,100,4,0,5,0,0,6,2,7,1,9,0]
let fixtureRequests: [[UInt8]] = [[10,1,0],[4,1],[4,9],[36,0,16],[8,1,2,3,4,5,6,7,9],[42],[40,7,1],[8,1,2,3,4,5,6,7,9]]
func fixtureReplies(mtu: Int = 514, ack: UInt8 = 0) -> [[UInt8]] {
    [[11,1] + le(mtu,2) + [ack],firmware,[5,9,211,72],[37,232,3,33],status,[43,7,2],[41,7,0,0,0,0] + table,status]
}

/// Exercise each packet and write callback separately, including the real ordering
/// where a notification arrives before its request's didWrite callback.
func exchange(_ core: inout BLEReadOnlyCheck, expected: [UInt8], reply: [UInt8], time: TimeInterval,
              packetLimit: Int = 514, ackPeriod: Int = 0, replyBeforeCallback: Bool = false) throws {
    guard let packet = try core.nextWrite(now: time) else { fatalError("No packet") }
    expect(packet == [0x81] + expected, "fixed read-only request bytes")
    expect(try core.nextWrite(now: time) == nil, "only one native write in flight")
    let fragments = try BLEPacketCodec.fragments(reply, packetLimit: packetLimit)
    if !replyBeforeCallback { try core.didWrite(now: time) }
    for (index, fragment) in fragments.enumerated() {
        try core.receive(fragment, now: time)
        if replyBeforeCallback && index == 0 {
            expect(try core.nextWrite(now: time) == nil, "notification held until native callback")
            try core.didWrite(now: time)
        }
        if index + 1 < fragments.count && ackPeriod > 0 && (index + 1) % ackPeriod == 0 {
            expect(try core.nextWrite(now: time) == [0], "periodic upstream acknowledgement")
            expect(try core.nextWrite(now: time) == nil, "ACK write paced by callback")
            try core.didWrite(now: time)
        }
    }
}

for limit in [20,23,185,512] {
    for mtu in [20,514] {
        for ack: UInt8 in [0,1,2,7] {
            for early in [false,true] {
                var core = try BLEReadOnlyCheck(platformWriteLimit: limit, now: 0)
                let replies = fixtureReplies(mtu: mtu, ack: ack)
                for index in fixtureRequests.indices {
                    try exchange(&core, expected: fixtureRequests[index], reply: replies[index], time: Double(index),
                        packetLimit: index == 0 ? 20 : mtu, ackPeriod: index == 0 ? 0 : Int(ack), replyBeforeCallback: early)
                }
                expect(core.complete && !core.failed, "bounded flow completes")
                expect(core.requestCount == 8, "exact request count")
                expect(core.result?.firmware == "G1L1FA2105AR", "firmware decoded")
                expect(core.result?.protocolMTU == mtu && core.result?.acknowledgementPeriod == Int(ack), "MTU high byte independent from ACK period")
                expect(core.result?.maximumMessage == 1000 && core.result?.securityRaw == 33, "setup values resolved")
                expect(core.result?.before == core.result?.after, "same diagnostic status")
                expect(core.result?.capabilities.requests == [4,8,12,14,48], "capabilities decoded")
                expect(try core.nextWrite(now: 8) == nil, "completion produces no additional writes")
            }
        }
    }
}

// Multi-part capability files retain their scoped handle and exact remaining count.
var paged = try BLEReadOnlyCheck(platformWriteLimit: 20, now: 0)
let initial = fixtureReplies()
for index in 0..<6 { try exchange(&paged, expected: fixtureRequests[index], reply: initial[index], time: Double(index)) }
let cut = 12
try exchange(&paged, expected: [40,7,1], reply: [41,7] + le(table.count-cut,4) + table.prefix(cut), time: 6)
try exchange(&paged, expected: [40,7,1], reply: [41,7,0,0,0,0] + table.dropFirst(cut), time: 7)
try exchange(&paged, expected: fixtureRequests.last!, reply: status, time: 8)
expect(paged.complete && paged.requestCount == 9, "scoped capability pagination")

// JSON capability encoding is observed in source and uses the same bounds.
var jsonCore = try BLEReadOnlyCheck(platformWriteLimit: 20, now: 0)
for index in 0..<5 { try exchange(&jsonCore, expected: fixtureRequests[index], reply: initial[index], time: Double(index)) }
try exchange(&jsonCore, expected: [42], reply: [43,7,1], time: 5)
let json = Array(#"{"version":9,"proto_version":1,"requests":[4,8,12,14],"mime":[1],"ifs":[1,2]}"#.utf8)
try exchange(&jsonCore, expected: [40,7,1], reply: [41,7,0,0,0,0] + json, time: 6)
try exchange(&jsonCore, expected: fixtureRequests.last!, reply: status, time: 7)
expect(jsonCore.complete && jsonCore.result?.capabilities.version == 9, "JSON table")

// Framing boundaries: exact packet multiples still mark the last fragment final.
for packetLimit in [2,3,20,185,514] {
    for size in [1,2,packetLimit-1,packetLimit,2*(packetLimit-1),min(4096,126*(packetLimit-1))] {
        let bytes = (0..<size).map { UInt8($0 & 255) }
        let packets = try BLEPacketCodec.fragments(bytes, packetLimit: packetLimit)
        expect(packets.count <= 127 && packets.allSatisfy { $0.count <= packetLimit }, "packet limits")
        expect(packets.last![0] & 128 == 128, "final flag")
        var codec = BLEPacketCodec(), rebuilt: [UInt8]?
        for packet in packets { rebuilt = try codec.receive(packet, ackPeriod: 2, packetLimit: packetLimit).message }
        expect(rebuilt == bytes, "framing round trip")
    }
}
rejects("sequence wrap") { _ = try BLEPacketCodec.fragments(Array(repeating: 9,count: 128), packetLimit: 2) }
for packet: [UInt8] in [[],[0],[0,9],[0x82,5],[0x81],[0x01,9],[0xff,9]] {
    var codec = BLEPacketCodec()
    if packet == [0x01,9] {
        _ = try codec.receive(packet, ackPeriod: 0, packetLimit: 20)
        rejects("duplicate sequence") { _ = try codec.receive(packet, ackPeriod: 0, packetLimit: 20) }
    } else { rejects("invalid envelope") { _ = try codec.receive(packet, ackPeriod: 0, packetLimit: 20) } }
}

// Every stage stops after rejection, timeout, interruption and unsolicited reply.
for interruptedStage in fixtureRequests.indices {
    for mode in 0..<5 {
        var core = try BLEReadOnlyCheck(platformWriteLimit: 20, now: 0)
        for index in 0..<interruptedStage { try exchange(&core, expected: fixtureRequests[index], reply: initial[index], time: Double(index)) }
        let now = Double(interruptedStage)
        switch mode {
        case 0:
            rejects("stage printer rejection") { try exchange(&core,expected:fixtureRequests[interruptedStage],reply:[1,fixtureRequests[interruptedStage][0],3],time:now) }
        case 1:
            rejects("stage wrong response") { try exchange(&core,expected:fixtureRequests[interruptedStage],reply:[99],time:now) }
        case 2: rejects("stage deadline") { try core.check(now: now+10) }
        case 3: core.stop()
        default:
            rejects("response before request") { try core.receive([0x81] + initial[interruptedStage], now: now) }
        }
        expect(core.failed && !core.complete, "failure is terminal")
        rejects("stopped check cannot produce another packet") { _ = try core.nextWrite(now: now+10) }
    }
}

let malformed: [(Int,[UInt8])] = [
    (0,[11,2,2,2,0]), (0,[11,1,2,2]), (0,[11,1,19,0,0]), (0,[11,1,20,0,128]),
    (1,[5,1,255]), (1,[5,1,1,0]), (2,[5,9,1,0]), (3,[37,0,0,33]),
    (4,[9,1,0,0,0,0]), (4,status + [3,50]), (5,[43,7,3]),
    (6,[41,8,0,0,0,0] + table), (6,[41,7,1,0,0,0]),
    (6,[41,7,0,0,1,0]), (6,[41,7,0,0,0,0] + table + tlv(1,[9,0])),
    (6,[41,7,0,0,0,0] + tlv(3,[1,4])),
    (7,status + [99])
]
for (stage, bad) in malformed {
    var core = try BLEReadOnlyCheck(platformWriteLimit: 20, now: 0)
    for index in 0..<stage { try exchange(&core,expected:fixtureRequests[index],reply:initial[index],time:Double(index)) }
    rejects("malformed response at stage \(stage)") { try exchange(&core,expected:fixtureRequests[stage],reply:bad,time:Double(stage)) }
    expect(core.failed, "malformed response terminal")
}

var globalDeadline = try BLEReadOnlyCheck(platformWriteLimit: 20, now: 0)
for index in 0..<6 { try exchange(&globalDeadline,expected:fixtureRequests[index],reply:initial[index],time:Double(index)*9) }
let repeatingTable: [UInt8] = [41,7] + le(65000,4) + [1]
try exchange(&globalDeadline,expected:[40,7,1],reply:repeatingTable,time:54)
rejects("overall deadline despite continuing exchanges") { try globalDeadline.check(now:60) }
var reversed = try BLEReadOnlyCheck(platformWriteLimit:20,now:1)
rejects("reversed clock") { try reversed.check(now:0) }
var callback = try BLEReadOnlyCheck(platformWriteLimit:20,now:0)
rejects("write completion without write") { try callback.didWrite(now:0) }
for limit in [0,1,19,65537] { rejects("invalid native write limit") { _ = try BLEReadOnlyCheck(platformWriteLimit:limit,now:0) } }

// Acknowledgements may themselves still be awaiting the platform callback when
// the final notification arrives. The next request cannot overtake that write.
var ackRace = try BLEReadOnlyCheck(platformWriteLimit:20,now:0)
try exchange(&ackRace,expected:fixtureRequests[0],reply:fixtureReplies(mtu:20,ack:1)[0],time:0)
_ = try ackRace.nextWrite(now:1); try ackRace.didWrite(now:1)
let splitFirmware = try BLEPacketCodec.fragments(firmware,packetLimit:10)
try ackRace.receive(splitFirmware[0],now:1)
expect(try ackRace.nextWrite(now:1) == [0], "ACK race starts acknowledgement")
try ackRace.receive(splitFirmware[1],now:1)
expect(try ackRace.nextWrite(now:1) == nil && ackRace.phase == "firmware", "final response waits for ACK callback")
try ackRace.didWrite(now:1)
expect(ackRace.phase == "model", "ACK callback releases held response")
expect(try ackRace.nextWrite(now:1) == [0x81,4,9], "next request follows acknowledged write")

// A strict codec rejects receive overflow, impossible sequence exhaustion and
// oversized notifications instead of resynchronizing or truncating silently.
var overlong = BLEPacketCodec()
_ = try overlong.receive([1] + Array(repeating:9,count:4096),ackPeriod:0,packetLimit:4097)
rejects("assembled receive overflow") { _ = try overlong.receive([0x82,9],ackPeriod:0,packetLimit:4097) }
var exhausted = BLEPacketCodec()
for index in 1...126 { _ = try exhausted.receive([UInt8(index),9],ackPeriod:0,packetLimit:20) }
rejects("nonfinal sequence127 cannot continue") { _ = try exhausted.receive([127,9],ackPeriod:0,packetLimit:20) }
var oversizedPacket = BLEPacketCodec()
rejects("notification exceeds negotiated packet bound") { _ = try oversizedPacket.receive([0x81] + Array(repeating:9,count:20),ackPeriod:0,packetLimit:20) }

// Diagnostic success reports busy/error/security data; it never grants readiness
// or changes printer state to force a successful result.
var diagnostic = try BLEReadOnlyCheck(platformWriteLimit:20,now:0)
var busy = status
busy[2] = 1; busy[7] = 7; busy[9] = 20; busy[13] = 5; busy[18] = 4
var diagnosticReplies = fixtureReplies()
diagnosticReplies[3] = [37,232,3,1]
diagnosticReplies[4] = busy; diagnosticReplies[7] = busy
for index in fixtureRequests.indices { try exchange(&diagnostic,expected:fixtureRequests[index],reply:diagnosticReplies[index],time:Double(index)) }
expect(diagnostic.complete && diagnostic.result?.securityRaw == 1, "raw weaksecurity reported only")
expect(diagnostic.result?.before.state == 7 && diagnostic.result?.before.flags == 1, "busyflags diagnostic preserved")

// Read-only handle exhaustion and inconsistent download lengths stop rather than
// issuing another arbitrary file read or looping without bound.
var manyChunks = try BLEReadOnlyCheck(platformWriteLimit:20,now:0)
for index in 0..<6 { try exchange(&manyChunks,expected:fixtureRequests[index],reply:initial[index],time:0) }
for index in 0..<64 {
    try exchange(&manyChunks,expected:[40,7,1],reply:[41,7] + le(1000-index,4) + [0],time:0)
}
rejects("capability page65 refused") { try exchange(&manyChunks,expected:[40,7,1],reply:[41,7] + le(936,4) + [0],time:0) }
var remainingMismatch = try BLEReadOnlyCheck(platformWriteLimit:20,now:0)
for index in 0..<6 { try exchange(&remainingMismatch,expected:fixtureRequests[index],reply:initial[index],time:0) }
try exchange(&remainingMismatch,expected:[40,7,1],reply:[41,7,5,0,0,0,1],time:0)
rejects("capability remaining mismatch") { try exchange(&remainingMismatch,expected:[40,7,1],reply:[41,7,0,0,0,0,1],time:0) }


// Cancellation after handing bytes to CoreBluetooth is terminal whether or not
// its write callback or the first response fragment has arrived.
for interruptedStage in fixtureRequests.indices {
    for point in 0..<3 {
        var core = try BLEReadOnlyCheck(platformWriteLimit:20,now:0)
        for index in 0..<interruptedStage { try exchange(&core,expected:fixtureRequests[index],reply:initial[index],time:0) }
        _ = try core.nextWrite(now:0)
        if point > 0 { try core.didWrite(now:0) }
        if point == 2 {
            let fragments = try BLEPacketCodec.fragments(initial[interruptedStage],packetLimit:2)
            try core.receive(fragments[0],now:0)
        }
        core.stop()
        expect(core.failed && !core.complete && core.result == nil, "postsend cancellation remains failed")
        rejects("late callback after cancellation") { try core.didWrite(now:0) }
        rejects("late notification after cancellation") { try core.receive([0x81,99],now:0) }
        rejects("no output after cancelled send") { _ = try core.nextWrite(now:0) }
    }
}

var terminal = diagnostic
let terminalBytes = terminal.rxBytes
terminal.stop()
try terminal.didWrite(now: 999)
try terminal.receive([0x81,99],now: 999)
expect(terminal.complete && !terminal.failed && terminal.result != nil && terminal.rxBytes == terminalBytes, "successful terminal cleanup idempotent")
expect(try terminal.nextWrite(now:999) == nil, "successful terminal state produces no writes")

print("BLE read-only core: \(checks) checks passed. No Bluetooth/device access.")
