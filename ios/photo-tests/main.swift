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
