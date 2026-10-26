import Foundation
func expectFailure(_ action: () throws -> Void) {
    do { try action(); fatalError("Expected failure") } catch {}
}
let firmware = Array("G1L1FA2105AR".utf8)
let payload: [UInt8] = [5, 1, UInt8(firmware.count)] + firmware
let frame: [UInt8] = [0x48,0x50,0x2b,1,UInt8(payload.count)] + payload
// Exact physical iOS response supplied by the user, 2026-10-26 19:21:22 UTC.
let observed: [UInt8] = [0x48,0x50,0x2b,0x01,0x0f,0x05,0x01,0x0c,0x47,0x31,0x4c,0x31,0x46,0x41,0x32,0x31,0x30,0x35,0x41,0x52]
assert(frame == observed)
for split in 1..<frame.count {
    var wire = IdentityWire()
    var transmitted: [UInt8] = []
    for _ in 0..<10 {
        _ = try wire.send { bytes in transmitted += bytes.prefix(2); return min(2,bytes.count) }
    }
    assert(transmitted == IdentityWire.request)
    let first = try wire.receive(Array(frame.prefix(split))); assert(first == nil)
    let second = try wire.receive(Array(frame.dropFirst(split))); assert(second == "G1L1FA2105AR")
}
var wire = IdentityWire()
_ = try wire.send { _ in 0 }; assert(wire.sent == 0)
expectFailure { _ = try wire.send { _ in -1 } }
assert(wire.sent == 0)
_ = try wire.send { $0.count }
for bytes: [UInt8] in [[0,0,0,1], [0x48,0x50,0x2b,3], [0x48,0x50,0x2b,1,0], frame + [0], [0x48,0x50,0x2b,1,3,5,1,127], [0x48,0x50,0x2b,1,3,1,4,3]] {
    var copy = wire
    expectFailure { _ = try copy.receive(bytes) }
}
var longHeader = wire
let wide = try longHeader.receive([0x48,0x50,0x2b,2,UInt8(payload.count),0] + payload); assert(wide == "G1L1FA2105AR")
var unsolicited = IdentityWire()
expectFailure { _ = try unsolicited.receive(frame) }
print("IdentityWire tests passed: partial/zero/error writes, no repeat, fragmented frames, strict response and bounds")
