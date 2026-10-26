import Foundation
import ImageIO
import UniformTypeIdentifiers
let args = CommandLine.arguments
let input = try Data(contentsOf: URL(fileURLWithPath: args[1]))
let root = URL(fileURLWithPath: args[2]); try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
for layout in PhotoLayout.allCases {
    for quality in [90, 95, 100] {
        let prepared = try PhotoPreparation.prepare(input, layout: layout, quality: quality)
        assert(prepared.preview.width == 768 && prepared.preview.height == 1152)
        assert(prepared.raster.colorSpace?.name == CGColorSpace.sRGB)
        if layout == .preserve {
            assert(prepared.placement.minX >= 48-0.001 && prepared.placement.minY >= 48-0.001)
        }
        let name = "\(layout.rawValue)-\(quality)"
        try prepared.jpeg.write(to: root.appendingPathComponent(name + ".jpg"))
        let url = root.appendingPathComponent(name + ".png")
        let dst = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil)!
        CGImageDestinationAddImage(dst, prepared.raster, nil); assert(CGImageDestinationFinalize(dst))
    }
}
print("Prepared all layouts and qualities")

// Sampling comes from SOF, never from the requested quality number.
func header(_ factors: [UInt8]) -> Data {
    let length = 8 + factors.count * 3
    var b: [UInt8] = [255,216,255,192,0,UInt8(length),8,4,128,3,0,UInt8(factors.count)]
    for (i, factor) in factors.enumerated() { b += [UInt8(i+1),factor,0] }
    return Data(b)
}
for (factors, prefix) in [([UInt8(17),17,17], "4:4:4"), ([33,17,17], "4:2:2"), ([34,17,17], "4:2:0"), ([17], "Grayscale")] {
    let data = header(factors)
    assert(JPEGDetails.sampling(data).hasPrefix(prefix))
    for n in 0..<data.count { assert(JPEGDetails.sampling(data.prefix(n)) == "Unknown") }
}
assert(JPEGDetails.sampling(Data([255,216,255,192,0,0])) == "Unknown")
assert(JPEGDetails.sampling(header([49,17,17])).hasPrefix("Other sampling"))
let sample = try PhotoPreparation.prepare(input, layout: .fill, quality: 100)
assert(JPEGDetails.sampling(sample.jpeg) != "Unknown")
print("JPEG sampling and malformed-header checks passed")
