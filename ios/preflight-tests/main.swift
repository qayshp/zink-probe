import Foundation
func refused(_ block: () throws -> Void) { do { try block(); fatalError("Expected failure") } catch {} }
func frame(_ payload: [UInt8], _ type: UInt8 = 2) -> [UInt8] {
    let width = type == 1 ? 1 : type == 2 ? 2 : 4
    return [72,80,43,type] + (0..<width).map { UInt8((payload.count >> ($0*8)) & 255) } + payload
}
let json = Array("{\"requests\":[12,14,48,44,58],\"mime\":[1],\"job_prop\":[1,3],\"job_name_max\":64}".utf8)
let tlv: [UInt8] = [3,6,0,5,12,14,48,44,58,7,2,0,1,1,8,3,0,2,1,3,20,2,0,64,0]
let replies: [[UInt8]] = [
 [5,1,12] + Array("G1L1FA2105AR".utf8), [5,9,211,72], [5,6] + Array(repeating: 7,count:16),
 [37,0,16,0], [43,9,1], [41,9,0,0,0,0] + json, [27,4,0],
 [9,1,0,0,0,0,2,1,3,65,5,0,0,6,1,7,1], [45], [59,1,0,0,1,0,9,0,0,0,3,0,1,0,0,0]]
let requests: [[UInt8]] = [[4,1],[4,9],[4,6],[36,0,16],[42],[40,9,1],[26,4],[8,1,2,3,5,6,7],[44],[58,1,0,0]]
for binary in [false,true] {
    var data = replies
    if binary { data[4] = [43,9,2]; data[5] = [41,9,0,0,0,0] + tlv }
    var preflight = try ReadOnlyPreflight(expectedDeviceID: String(repeating:"07",count:16))
    for (index,reply) in data.enumerated() {
        let request = try preflight.next(); assert(request == requests[index])
        refused { _ = try preflight.next() }
        // Every split of response and one-byte output writes, both length encodings.
        for type: UInt8 in [1,2,3] {
            let encoded = frame(reply,type)
            for split in 0...encoded.count {
                var wire = try AccessoryExchange(payload: request, now: 0)
                var sent: [UInt8] = []
                try wire.write(now: 0) { _ in 0 }
                for _ in frame(request,1) { try wire.write(now: 1) { bytes in sent.append(bytes[0]); return 1 } }
                assert(sent == frame(request,1))
                let first = try wire.receive(Array(encoded.prefix(split)), now: 2)
                let result = split == encoded.count ? first : try wire.receive(Array(encoded.dropFirst(split)), now: 2)
                assert(result == reply)
                refused { try wire.write(now: 3) { _ in 1 } }
            }
        }
        try preflight.accept(reply)
    }
    assert(preflight.complete && preflight.identityBound && preflight.battery == 65 && preflight.pages == 9)
    refused { _ = try preflight.next() }
}
// Malformed responses stop every preflight stage permanently.
for index in replies.indices {
    for bad in [[], [1,requests[index][0],7], Array(replies[index].dropLast())] as [[UInt8]] {
        var p = try ReadOnlyPreflight()
        for r in replies.prefix(index) { _ = try p.next(); try p.accept(r) }
        _ = try p.next(); refused { try p.accept(bad) }; assert(p.failed)
        refused { _ = try p.next() }
    }
}
func failAt(_ index: Int, _ reply: [UInt8], expected: String? = nil) throws {
    var p = try ReadOnlyPreflight(expectedDeviceID: expected)
    for r in replies.prefix(index) { _ = try p.next(); try p.accept(r) }
    _ = try p.next(); refused { try p.accept(reply) }
}
try failAt(1,[5,9,0,0])
try failAt(2,replies[2],expected:String(repeating:"00",count:16))
try failAt(3,[37,0,0,0]); try failAt(3,[37,0,16,1])
try failAt(6,[27,4,1]); try failAt(8,[45,1,0])
for (offset,value): (Int,UInt8) in [(2,1),(7,7),(9,29),(9,101),(14,4),(16,4)] {
    var bad = replies[7]; bad[offset] = value; try failAt(7,bad)
}
try failAt(5,[41,9,1,0,0,0]) // no progress
try failAt(5,[41,9,0,0,0,0] + Array("{}".utf8))
try failAt(9,[59,1,0,0]) // no counters
for bytes in [[0,0,0,1], [72,80,43,4], [72,80,43,2,255,255], frame([5])+frame([5])] {
    var wire = try AccessoryExchange(payload:[4,1],now:0)
    try wire.write(now:0) { $0.count }
    refused { _ = try wire.receive(bytes,now:1) }
    assert(wire.ended)
}
for count in [-1,99] {
    var wire = try AccessoryExchange(payload:[4,1],now:0)
    refused { try wire.write(now:0) { _ in count } }; assert(wire.ended)
}
var timed = try AccessoryExchange(payload:[4,1],now:0)
refused { try timed.check(now:10) }
var early = try AccessoryExchange(payload:[4,1],now:0)
refused { _ = try early.receive(frame([5]),now:1) }
for sentCount in 0...7 {
    var wire = try AccessoryExchange(payload:[4,1],now:0)
    if sentCount > 0 { try wire.write(now:0) { _ in sentCount } }
    wire.stop(); refused { try wire.write(now:1) { $0.count } }
}
print("Preflight/framing: JSON/TLV success, all frame splits, partial/zero writes, invalid states, mismatched identity, interruption and timeout passed")
// Multi-chunk capabilities and metrics pages, plus repeated iterator rejection.
var paged = try ReadOnlyPreflight()
for r in replies.prefix(5) { _ = try paged.next(); try paged.accept(r) }
_ = try paged.next()
let cut = 20, remaining = json.count - 20
try paged.accept([41,9,UInt8(remaining),0,0,0] + json.prefix(cut))
let more = try paged.next(); assert(more == [40,9,1])
try paged.accept([41,9,0,0,0,0] + json.dropFirst(cut))
for r in replies[6...8] { _ = try paged.next(); try paged.accept(r) }
_ = try paged.next(); try paged.accept([59,1,1,0,1,0,9,0,0,0])
let nextMetrics = try paged.next(); assert(nextMetrics == [58,1,1,0])
try paged.accept([59,1,0,0,3,0,1,0,0,0]); assert(paged.complete)
var loop = try ReadOnlyPreflight()
for r in replies.prefix(9) { _ = try loop.next(); try loop.accept(r) }
_ = try loop.next(); try loop.accept([59,1,1,0])
_ = try loop.next(); refused { try loop.accept([59,1,1,0]) }
for key in ["requests","mime","job_prop"] {
    var obj = try JSONSerialization.jsonObject(with: Data(json)) as! [String:Any]
    obj[key] = [Int]()
    try failAt(5,[41,9,0,0,0,0] + Array(try JSONSerialization.data(withJSONObject:obj)))
}
var large = try AccessoryExchange(payload:Array(repeating:4,count:300),now:0)
var captured: [UInt8] = []
try large.write(now:0) { captured = $0; return $0.count }
assert(captured == frame(Array(repeating:4,count:300),2))
print("Pagination, missing capabilities and two-byte output frame checks passed")
