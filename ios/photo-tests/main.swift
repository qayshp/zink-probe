import Foundation
import CoreGraphics
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

// Distinct corners make clockwise, counterclockwise and mirrored results
// distinguishable even after the prepared JPEG is decoded.
enum CornerColor {
    case red, green, blue, yellow

    var channels: [UInt8] {
        switch self {
        case .red: [255, 0, 0]
        case .green: [0, 255, 0]
        case .blue: [0, 0, 255]
        case .yellow: [255, 255, 0]
        }
    }
}

let colorSpace = CGColorSpace(name: CGColorSpace.sRGB)!
let rgbx = CGImageAlphaInfo.noneSkipLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue
let fixture = CGContext(data: nil, width: 80, height: 120, bitsPerComponent: 8,
                        bytesPerRow: 0, space: colorSpace, bitmapInfo: rgbx)!
let originalColors: [CornerColor] = [.red, .green, .blue, .yellow]
for (index, color) in originalColors.enumerated() {
    let channels = color.channels.map { CGFloat($0) / 255 }
    fixture.setFillColor(red: channels[0], green: channels[1], blue: channels[2], alpha: 1)
    fixture.fill(CGRect(x: (index % 2) * 40, y: index < 2 ? 60 : 0, width: 40, height: 60))
}

func encodeFixture(type: UTType, orientation: CGImagePropertyOrientation = .up) -> Data {
    let bytes = NSMutableData()
    let writer = CGImageDestinationCreateWithData(bytes, type.identifier as CFString, 1, nil)!
    CGImageDestinationAddImage(writer, fixture.makeImage()!, [
        kCGImagePropertyOrientation: orientation.rawValue,
        kCGImageDestinationLossyCompressionQuality: 1.0
    ] as CFDictionary)
    precondition(CGImageDestinationFinalize(writer))
    return bytes as Data
}

func matches(_ color: CornerColor, at point: CGPoint, in image: CGImage) -> Bool {
    let pixel = image.cropping(to: CGRect(x: floor(point.x), y: floor(point.y), width: 1, height: 1))!
    let context = CGContext(data: nil, width: 1, height: 1, bitsPerComponent: 8,
                            bytesPerRow: 4, space: colorSpace, bitmapInfo: rgbx)!
    context.draw(pixel, in: CGRect(x: 0, y: 0, width: 1, height: 1))
    let rgb = context.data!.assumingMemoryBound(to: UInt8.self)
    return color.channels.enumerated().allSatisfy { abs(Int(rgb[$0.offset]) - Int($0.element)) < 20 }
}

func checkRotation(_ photo: PreparedPhoto, size: CGSize, corners: [CornerColor]) {
    precondition(photo.sourceSize == size)
    precondition(photo.preview.width == 768 && photo.preview.height == 1152)
    for (index, color) in corners.enumerated() {
        let point = CGPoint(
            x: photo.placement.minX + photo.placement.width * (index % 2 == 0 ? 0.25 : 0.75),
            y: photo.placement.minY + photo.placement.height * (index < 2 ? 0.25 : 0.75)
        )
        precondition(matches(color, at: point, in: photo.preview),
                     "Incorrect decoded JPEG corner \(index) for \(size)")
    }
}

let upright = encodeFixture(type: .png)
let portrait = CGSize(width: 80, height: 120)
let landscape = CGSize(width: 120, height: 80)
let clockwiseColors: [CornerColor] = [.blue, .red, .yellow, .green]
let clockwise = try PhotoPreparation.prepare(upright, layout: .preserve, quality: 100, rotation: .right)
checkRotation(clockwise, size: landscape, corners: clockwiseColors)
precondition(abs(clockwise.placement.width - 672) < 0.001)
precondition(abs(clockwise.placement.height - 448) < 0.001)
checkRotation(try PhotoPreparation.prepare(upright, layout: .fit, quality: 100, rotation: .left),
              size: landscape, corners: [.green, .yellow, .red, .blue])
checkRotation(try PhotoPreparation.prepare(upright, layout: .fill, quality: 100, rotation: .halfTurn),
              size: portrait, corners: [.yellow, .blue, .green, .red])

let exifClockwise = encodeFixture(type: .jpeg, orientation: .right)
checkRotation(try PhotoPreparation.prepare(exifClockwise, layout: .fit, quality: 100),
              size: landscape, corners: clockwiseColors)
checkRotation(try PhotoPreparation.prepare(exifClockwise, layout: .fit, quality: 100, rotation: .left),
              size: portrait, corners: originalColors)
print("Manual rotations, layout placement and EXIF composition passed")

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
