import Foundation
import ImageIO
import UniformTypeIdentifiers

/// Validated, immutable submission input. Image preparation itself remains in PhotoPreparation.
struct PreparedJobImage {
    let jpeg: Data
    let sampling: String
    init(jpeg: Data) throws {
        func require(_ value: Bool) throws { if !value { throw ReadOnlyPreflight.Failure.invalid("Expected complete 768×1152, 8-bit baseline sRGB JPEG") } }
        try require((4...16*1024*1024).contains(jpeg.count))
        let b = Array(jpeg)
        try require(b.starts(with:[255,216]) && b.suffix(2) == [255,217])
        var p = 2, found = false, sample = "", scan = false
        while p < b.count - 2 {
            try require(b[p] == 255)
            while p < b.count && b[p] == 255 { p += 1 }
            try require(p + 3 <= b.count)
            let marker = b[p], length = Int(b[p+1])*256 + Int(b[p+2]); p += 3
            try require(length >= 2 && p + length - 2 <= b.count)
            let body = Array(b[p..<p+length-2])
            if marker == 192 {
                try require(!found && body.count == 15)
                try require(Array(body.prefix(6)) == [8,4,128,3,0,3])
                try require(body[6] == 1 && body[9] == 2 && body[12] == 3 && body[10] == 17 && body[13] == 17)
                guard let label = [UInt8(17):"4:4:4",33:"4:2:2",34:"4:2:0"][body[7]] else { throw ReadOnlyPreflight.Failure.invalid("Unsupported JPEG sampling") }
                sample = label; found = true
            } else if (192...207).contains(marker) && ![196,200,204].contains(marker) {
                try require(false)
            } else if marker == 218 {
                try require(found && body.count == 10 && body[0] == 3 && body.suffix(3) == [0,63,0]); scan = true; break
            }
            p += length - 2
        }
        try require(found && scan)
        guard let source = CGImageSourceCreateWithData(jpeg as CFData,nil),
              CGImageSourceGetType(source) as String? == UTType.jpeg.identifier,
              CGImageSourceGetCount(source) == 1,
              let image = CGImageSourceCreateImageAtIndex(source,0,[kCGImageSourceShouldCacheImmediately:true] as CFDictionary) else { throw ReadOnlyPreflight.Failure.invalid("JPEG could not be decoded") }
        try require(CGImageSourceGetStatus(source) == .statusComplete && CGImageSourceGetStatusAtIndex(source,0) == .statusComplete)
        try require(image.width == 768 && image.height == 1152 && image.bitsPerComponent == 8 && image.colorSpace?.name == CGColorSpace.sRGB)
        let properties = CGImageSourceCopyPropertiesAtIndex(source,0,nil) as? [CFString:Any]
        try require((properties?[kCGImagePropertyOrientation] as? Int ?? 1) == 1)
        self.jpeg = jpeg; sampling = sample
    }
}
