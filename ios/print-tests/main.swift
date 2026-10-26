import Foundation
struct Exchange: Decodable { let request: [UInt8]; let reply: [UInt8] }
struct Fixture: Decodable { let maximum: Int; let jpeg: [UInt8]; let exchanges: [Exchange] }
let fixtures = try JSONDecoder().decode([Fixture].self, from: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1])))
func refused(_ action: () throws -> Void) {
    do { try action(); fatalError("Expected rejection") } catch { }
}
for fixture in fixtures {
    func fresh() throws -> UploadPlan {
        try UploadPlan(preparedJPEG: Data(fixture.jpeg), maximum: fixture.maximum, name: "Select café", nameLimit: 64)
    }
    var plan = try fresh()
    for exchange in fixture.exchanges {
        let request = try plan.nextMessage()
        assert(request == exchange.request)
        refused { _ = try plan.nextMessage() } // pending cannot be resent
        try plan.accept(exchange.reply)
    }
    assert(plan.phase == .uploaded && plan.offset == fixture.jpeg.count)
    refused { _ = try plan.nextMessage() }
    // Corrupt each response independently after replaying its valid prefix.
    for index in fixture.exchanges.indices {
        var invalid: [[UInt8]] = [[], [1,99,7], [1,fixture.exchanges[index].request[0],7], Array(fixture.exchanges[index].reply.dropLast())]
        if fixture.exchanges[index].request[0] == 14 {
            for field in [1,2,3,7] {
                var corrupt = fixture.exchanges[index].reply; corrupt[field] = 255
                invalid.append(corrupt)
            }
        }
        for bad in invalid {
            var broken = try fresh()
            for earlier in fixture.exchanges.prefix(index) {
                _ = try broken.nextMessage(); try broken.accept(earlier.reply)
            }
            _ = try broken.nextMessage()
            refused { try broken.accept(bad) }
            assert(broken.phase == .stopped)
            refused { _ = try broken.nextMessage() }
        }
    }
    var stopped = try fresh(); _ = try stopped.nextMessage(); stopped.stop()
    refused { _ = try stopped.nextMessage() }
    refused { try stopped.accept(fixture.exchanges[0].reply) }
}
print("Swift upload traces match Python: chunks, UTF-8 name, negotiated limits, optional empty final, failures and no resend")
let data = Data(fixtures[0].jpeg)
for (maximum, name, limit) in [(5,"ok",64), (32,"",64), (32,"bad\nname",64), (32,"é",1)] {
    refused { _ = try UploadPlan(preparedJPEG: data, maximum: maximum, name: name, nameLimit: limit) }
}
var zero = try UploadPlan(preparedJPEG: data, maximum: 32, name: "ok", nameLimit: 64)
_ = try zero.nextMessage()
refused { try zero.accept([13,7,0,0]) }
// Reaching total with status=1 permits one empty final chunk, never a loop.
let last = fixtures.first { $0.exchanges.last?.request.count == 2 }!
var ending = try UploadPlan(preparedJPEG: Data(last.jpeg), maximum: last.maximum, name: "Select café", nameLimit: 64)
for exchange in last.exchanges.dropLast() { _ = try ending.nextMessage(); try ending.accept(exchange.reply) }
_ = try ending.nextMessage()
var incomplete = last.exchanges.last!.reply; incomplete[2] = 1
try ending.accept(incomplete)
refused { _ = try ending.nextMessage() }
assert(ending.phase == .stopped)
