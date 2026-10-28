import Foundation

/// Framed in-memory peer for tests and the explicitly simulated Share flow.
/// No Bluetooth, sockets, native streams or real printer adapters.
final class SimulatedPrinter {
    let device: String
    init(deviceID: String = String(repeating:"07",count:16)) { device = deviceID }
    var input: [UInt8] = []
    var output: [UInt8] = []
    var requests: [[UInt8]] = []
    var pages = 13, calibrations = 2, job = 16, received = 0, total = 0, observations = 0
    var uploadedData: [UInt8] = []
    var uploaded = false, printing = false
    var neverPrint = false, foreignJob = false, extraPage = false, changedCalibration = false
    var mismatchIdentity = false, paused = false, badFinalOffset = false, droppedOpcode: UInt8?
    var dropFinalAck = false
    var initialFlags = 0
    var firmware = "G1L1FA2105AR"
    var requireEmptyFinal = false
    var maximum = 1000
    let capability: [UInt8] = [3,6,0,5,12,14,48,44,58,7,2,0,1,1,8,3,0,2,1,3,20,2,0,16,0]
    var startCount: Int { requests.filter { $0.first == 12 }.count }
    var mutationCount: Int { requests.filter { [UInt8(12),14,48].contains($0.first ?? 0) }.count }
    static func le(_ value: Int, _ width: Int) -> [UInt8] { UploadPlan.little(value,bytes:width) }
    static func frame(_ payload: [UInt8]) -> [UInt8] {
        [72,80,43] + (payload.count < 256 ? [1,UInt8(payload.count)] : [2,UInt8(payload.count & 255),UInt8(payload.count >> 8)]) + payload
    }
    func write(_ bytes: [UInt8], limit: Int = 13) -> Int {
        let count = min(limit,bytes.count)
        input += bytes.prefix(count)
        if input.count >= 5 {
            precondition(input.prefix(3) == [72,80,43])
            let header = input[3] == 1 ? 5 : 6
            if input.count >= header {
                let length = Int(input[4]) + (header == 6 ? Int(input[5])*256 : 0)
                if input.count == header + length {
                    let payload = Array(input.dropFirst(header)); input = []
                    requests.append(payload)
                    let reply = respond(payload)
                    if droppedOpcode != payload[0] && !(dropFinalAck && payload[0] == 14 && uploaded) { output += Self.frame(reply) }
                }
            }
        }
        return count
    }
    func respond(_ r: [UInt8]) -> [UInt8] {
        func scalar(_ tag: UInt8, _ value: Int, _ width: Int) -> [UInt8] { [tag] + Self.le(value,width) }
        switch r[0] {
        case 4:
            switch r[1] {
            case 1: return [5,1,UInt8(firmware.utf8.count)] + Array(firmware.utf8)
            case 9: return [5,9,211,72]
            case 6:
                let id = mismatchIdentity ? String(repeating:"08",count:16) : device
                return [5,6] + stride(from:0,to:32,by:2).map { offset in
                    let start = id.index(id.startIndex,offsetBy:offset)
                    return UInt8(id[start..<id.index(start,offsetBy:2)],radix:16)!
                }
            default: fatalError("Unexpected attribute")
            }
        case 36: return [37] + Self.le(maximum,2) + [33]
        case 42: return [43,9,2]
        case 40: return [41,9,0,0,0,0] + capability
        case 26: return [27,4,paused ? 1 : 0]
        case 8:
            if uploaded {
                observations += 1
                printing = !neverPrint && observations <= 2
                if observations == 3 && !neverPrint { pages += extraPage ? 2 : 1 }
                if changedCalibration { calibrations = 3 }
            }
            return [9] + scalar(1,printing ? 4 : initialFlags,4) + scalar(2,printing ? 7 : 1,1)
                + scalar(3,72,1) + scalar(5,foreignJob && uploaded ? 999 : printing ? job : 0,2)
                + scalar(6,1,1) + scalar(7,printing ? 4 : 1,1)
        case 44: return printing ? [45] + Self.le(job,2) : [45]
        case 58: return [59,1,0,0] + Self.le(1,2) + Self.le(pages,4) + Self.le(3,2) + Self.le(calibrations,4)
        case 12:
            total = r[2...5].enumerated().reduce(0) { $0 | (Int($1.element) << ($1.offset*8)) }
            job += 1; received = 0; uploadedData = []; observations = 0; uploaded = false
            return [13,7] + Self.le(job,2)
        case 48: return [49]
        case 14:
            uploadedData += r.dropFirst(2)
            received += r.count-2
            uploaded = received == total && (!requireEmptyFinal || r.count == 2)
            return [15,7,uploaded ? 2 : 1] + Self.le(badFinalOffset ? received+1 : received,4) + Self.le(total,4)
        default: fatalError("Unexpected opcode \(r[0])")
        }
    }
    func deliver(to coordinator: SubmissionCoordinator, now: TimeInterval, limit: Int = 37) {
        guard !output.isEmpty else { return }
        let count = min(output.count,limit), chunk = Array(output.prefix(count)); output.removeFirst(count)
        coordinator.receive(chunk,now:now)
    }
}
