import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

func check(_ condition: Bool, file: StaticString = #file, line: UInt = #line) {
    precondition(condition, file: file, line: line)
}

func refuses(_ body: () throws -> Void) {
    do {
        try body()
        fatalError("Expected the draft operation to be rejected")
    } catch {}
}

func image(gray: CGFloat) throws -> PreparedJobImage {
    let space = CGColorSpace(name: CGColorSpace.sRGB)!
    let context = CGContext(data: nil, width: 768, height: 1152, bitsPerComponent: 8,
                            bytesPerRow: 0, space: space,
                            bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
    context.setFillColor(CGColor(gray: gray, alpha: 1))
    context.fill(CGRect(x: 0, y: 0, width: 768, height: 1152))
    let bytes = NSMutableData()
    let destination = CGImageDestinationCreateWithData(bytes, UTType.jpeg.identifier as CFString, 1, nil)!
    CGImageDestinationAddImage(destination, context.makeImage()!,
                               [kCGImageDestinationLossyCompressionQuality: 1] as CFDictionary)
    check(CGImageDestinationFinalize(destination))
    return try PreparedJobImage(jpeg: bytes as Data)
}

let first = try BLEPilotDraft(id: UUID(), image: image(gray: 0.25),
                              settings: .init(layout: "Preserve edges", quality: 100))
let second = try BLEPilotDraft(id: UUID(uuidString: "F2A37C78-28F7-4360-A6C1-06E7EDF7601E")!,
                               image: image(gray: 0.75), settings: .init(layout: "Borderless", quality: 95))
if CommandLine.arguments.count == 3, CommandLine.arguments[1] == "replace-and-exit" {
    let url = URL(fileURLWithPath: CommandLine.arguments[2])
    try BLEPilotDraftStore(url: url).save(second)
    _exit(0)
}

let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
defer { try? FileManager.default.removeItem(at: directory) }
let url = directory.appendingPathComponent("draft.plist")
let store = BLEPilotDraftStore(url: url)

func checkSaved(_ expected: BLEPilotDraft) throws {
    let reopened = try BLEPilotDraftStore(url: url).load()
    check(reopened?.id == expected.id)
    check(reopened?.settings == expected.settings)
    check(reopened?.image.jpeg == expected.image.jpeg)
    check(reopened?.image.sampling == expected.image.sampling)
}

func dictionary() throws -> [String: Any] {
    let bytes = try Data(contentsOf: url)
    return try PropertyListSerialization.propertyList(from: bytes, format: nil) as! [String: Any]
}

func mutate(_ change: (inout [String: Any]) -> Void) throws {
    var values = try dictionary()
    change(&values)
    let bytes = try PropertyListSerialization.data(fromPropertyList: values, format: .binary, options: 0)
    try bytes.write(to: url)
}

check(try store.load() == nil)
try store.discard(id: first.id)
try store.save(first)
try checkSaved(first)
check(try Set(dictionary().keys) == ["version", "id", "jpeg", "digest", "settings"])

// A failed replacement retains the prior prepared image.
let invalid = BLEPilotDraft(id: second.id, image: second.image, settings: .init(layout: "Borderless", quality: 99))
refuses { try store.save(invalid) }
try checkSaved(first)

// Another process completes the atomic replacement and exits without cleanup.
let replacement = Process()
replacement.executableURL = URL(fileURLWithPath: CommandLine.arguments[0]).standardizedFileURL
replacement.arguments = ["replace-and-exit", url.path]
try replacement.run()
replacement.waitUntilExit()
check(replacement.terminationStatus == 0)
try checkSaved(second)
try store.discard(id: first.id)
try checkSaved(second)
try store.discard(id: second.id)
check(try store.load() == nil)

// Shape, digest and the underlying JPEG are each validated independently.
try store.save(first)
try mutate { $0["version"] = 2 }
refuses { _ = try store.load() }
try store.save(first)
try mutate { $0["digest"] = String(repeating: "0", count: 64) }
refuses { _ = try store.load() }
refuses { try store.discard(id: first.id) }
try store.save(first)
try mutate {
    let invalidJPEG = Data([255, 216, 255, 217])
    $0["jpeg"] = invalidJPEG
    $0["digest"] = JobJournal.digest(invalidJPEG)
}
refuses { _ = try store.load() }
try store.save(first)
let partial = try FileHandle(forWritingTo: url)
try partial.truncate(atOffset: 4)
try partial.close()
refuses { _ = try store.load() }
try store.save(first)
let oversized = try FileHandle(forWritingTo: url)
try oversized.truncate(atOffset: 32 * 1024 * 1024)
try oversized.close()
refuses { _ = try store.load() }
try store.save(second)
try checkSaved(second)

print("Prepared photo drafts passed: exact bytes and settings after reopening, replacement across abrupt exit, obsolete discard, corruption, and size limits")
