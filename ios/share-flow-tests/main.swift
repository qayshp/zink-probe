import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

@main
struct ShareFlowTests {
    static func jpeg() -> Data {
        let context = CGContext(data:nil,width:768,height:1152,bitsPerComponent:8,bytesPerRow:0,space:CGColorSpace(name:CGColorSpace.sRGB)!,bitmapInfo:CGImageAlphaInfo.noneSkipLast.rawValue)!
        context.setFillColor(CGColor(gray:0.5,alpha:1)); context.fill(CGRect(x:0,y:0,width:768,height:1152))
        let data = NSMutableData(), destination = CGImageDestinationCreateWithData(data,UTType.jpeg.identifier as CFString,1,nil)!
        CGImageDestinationAddImage(destination,context.makeImage()!,[kCGImageDestinationLossyCompressionQuality:1] as CFDictionary)
        precondition(CGImageDestinationFinalize(destination)); return data as Data
    }
    static func finish(_ driver: SimulatedSubmission) async -> SimulationSnapshot {
        var result = await driver.snapshot()
        for _ in 0..<10000 {
            if !result.running { return result }
            result = await driver.advance()
        }
        fatalError("Simulation failed to terminate")
    }
    static func main() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
        defer { try? FileManager.default.removeItem(at:root) }
        let image = jpeg()
        for scenario in SimulationScenario.allCases {
            let id = UUID(), url = root.appendingPathComponent("\(scenario.rawValue).sqlite")
            let driver = SimulatedSubmission(id:id,jpeg:image,journalURL:url)
            let review = await driver.advance()
            assert(review.state == "review" && !review.confirmed && review.requests == 0 && review.realPrinterBytes == 0)
            assert(!FileManager.default.fileExists(atPath:url.path))
            _ = await driver.confirm(scenario:scenario)
            let repeated = await driver.confirm(scenario:scenario)
            assert(repeated.duplicateBlocked)
            let result = await finish(driver)
            assert(result.printStarts == 1 && result.realPrinterBytes == 0)
            assert(result.state == (scenario == .success ? "completed" : "uncertain"))
            let duplicate = await driver.checkDuplicate()
            assert(duplicate.duplicateBlocked && duplicate.printStarts == 1)
            if scenario != .success {
                _ = await driver.recover()
                let recovered = await finish(driver)
                assert(recovered.state == "uncertain" && recovered.printStarts == 1 && recovered.realPrinterBytes == 0)
            }
            // A second instance with the same review/virtual target cannot replay.
            let reopened = SimulatedSubmission(id:id,jpeg:image,journalURL:url)
            let blocked = await reopened.confirm(scenario:.success)
            assert(blocked.state == "blocked" && blocked.printStarts == 0)
        }
        let before = SimulatedSubmission(id:UUID(),jpeg:image,journalURL:root.appendingPathComponent("before.sqlite"))
        _ = await before.cancel(); let cancelled = await before.confirm(scenario:.success)
        assert(!cancelled.running && cancelled.requests == 0)
        let interrupted = SimulatedSubmission(id:UUID(),jpeg:image,journalURL:root.appendingPathComponent("cancel.sqlite"))
        _ = await interrupted.confirm(scenario:.success)
        var snapshot = await interrupted.snapshot()
        for _ in 0..<10000 {
            if snapshot.acknowledgedBytes > 0 { break }
            snapshot = await interrupted.advance(steps:1)
        }
        assert(snapshot.acknowledgedBytes > 0 && snapshot.running)
        let stopped = await interrupted.cancel()
        let after = await interrupted.advance()
        assert(stopped.state == "uncertain" && after.requests == stopped.requests && after.printStarts == 1)
        let duplicate = await interrupted.checkDuplicate(); assert(duplicate.duplicateBlocked)
        let concurrent = SimulatedSubmission(id:UUID(),jpeg:image,journalURL:root.appendingPathComponent("concurrent.sqlite"))
        async let first = concurrent.confirm(scenario:.success)
        async let second = concurrent.confirm(scenario:.success)
        _ = await (first,second)
        let once = await finish(concurrent)
        assert(once.state == "completed" && once.printStarts == 1 && once.duplicateBlocked)
        let invalid = SimulatedSubmission(id:UUID(),jpeg:Data([0,1,2]),journalURL:root.appendingPathComponent("invalid.sqlite"))
        let refused = await invalid.confirm(scenario:.success)
        assert(refused.state == "blocked" && refused.requests == 0 && refused.printStarts == 0)
        assert(!FileManager.default.fileExists(atPath:root.appendingPathComponent("invalid.sqlite").path))
        let unusable = root.appendingPathComponent("not-a-directory")
        try Data([1]).write(to:unusable)
        let storage = SimulatedSubmission(id:UUID(),jpeg:image,journalURL:unusable.appendingPathComponent("store.sqlite"))
        let failed = await storage.confirm(scenario:.success)
        assert(failed.state == "blocked" && failed.requests == 0 && failed.printStarts == 0)
        print("Share-flow checks passed: explicit confirmation, fixed memory peer, 3 scenarios, cancellation, concurrent/duplicate taps, reopen, read-only recovery and invalid/storage refusal")
    }
}
