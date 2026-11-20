import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

struct PreparedPhoto {
    let jpeg: Data
    let raster: CGImage
    let preview: CGImage
    let sourceSize: CGSize
    let placement: CGRect
}
enum PhotoLayout: String, CaseIterable { case fill = "Borderless", fit = "Fit", preserve = "Preserve edges" }

enum PhotoRotation: Int, CaseIterable {
    case none, right, halfTurn, left

    var toLeft: Self { Self.allCases[(rawValue + 3) % 4] }
    var toRight: Self { Self.allCases[(rawValue + 1) % 4] }
    var swapsAxes: Bool { self == .right || self == .left }
    var quartzAngle: CGFloat {
        switch self {
        case .none: return 0
        case .right: return -.pi / 2
        case .halfTurn: return .pi
        case .left: return .pi / 2
        }
    }
}

enum PhotoPreparation {
    enum Failure: LocalizedError {
        case invalid
        var errorDescription: String? { "Cannot prepare this image. Use a single SDR JPEG, PNG or HEIC image under 50 MB and 80 megapixels." }
    }
    static func prepare(_ data: Data, layout: PhotoLayout, quality: Int,
                        rotation: PhotoRotation = .none) throws -> PreparedPhoto {
        guard data.count <= 50_000_000, (1...100).contains(quality),
              let source = CGImageSourceCreateWithData(data as CFData, nil),
              let type = CGImageSourceGetType(source) as String?,
              [UTType.jpeg.identifier, UTType.png.identifier, UTType.heic.identifier].contains(type),
              (type == UTType.heic.identifier || CGImageSourceGetCount(source) == 1),
              let props = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let w = props[kCGImagePropertyPixelWidth] as? Int,
              let h = props[kCGImagePropertyPixelHeight] as? Int,
              w > 0, h > 0, w <= 80000, h <= 80000, w * h <= 80_000_000,
              let image = CGImageSourceCreateThumbnailAtIndex(source, 0, [
                kCGImageSourceCreateThumbnailFromImageAlways: true,
                kCGImageSourceCreateThumbnailWithTransform: true,
                kCGImageSourceThumbnailMaxPixelSize: min(4096, max(w, h)),
                kCGImageSourceShouldCacheImmediately: true
              ] as CFDictionary),
              image.bitsPerComponent == 8,
              let space = CGColorSpace(name: CGColorSpace.sRGB),
              let context = CGContext(data: nil, width: 768, height: 1152, bitsPerComponent: 8,
                  bytesPerRow: 768 * 4, space: space,
                  bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { throw Failure.invalid }
        let width = Double(rotation.swapsAxes ? image.height : image.width)
        let height = Double(rotation.swapsAxes ? image.width : image.height)
        let inset = layout == .preserve ? 48.0 : 0
        let sx = (768 - 2 * inset) / width, sy = (1152 - 2 * inset) / height
        let scale = layout == .fill ? max(sx, sy) : min(sx, sy)
        let rect = CGRect(x: (768-width*scale)/2, y: (1152-height*scale)/2,
                          width: width*scale, height: height*scale)
        context.setFillColor(CGColor(gray: 1, alpha: 1))
        context.fill(CGRect(x: 0, y: 0, width: 768, height: 1152))
        context.interpolationQuality = .high
        context.setRenderingIntent(.relativeColorimetric)
        let drawWidth = rotation.swapsAxes ? rect.height : rect.width
        let drawHeight = rotation.swapsAxes ? rect.width : rect.height
        context.translateBy(x: rect.midX, y: rect.midY)
        context.rotate(by: rotation.quartzAngle)
        context.draw(image, in: CGRect(x: -drawWidth / 2, y: -drawHeight / 2,
                                       width: drawWidth, height: drawHeight))
        guard let raster = context.makeImage() else { throw Failure.invalid }
        let output = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(output, UTType.jpeg.identifier as CFString, 1, nil) else { throw Failure.invalid }
        // Native ImageIO quality is not numerically equivalent to libjpeg quality.
        CGImageDestinationAddImage(destination, raster, [kCGImageDestinationLossyCompressionQuality: Double(quality)/100, kCGImagePropertyExifDictionary: [kCGImagePropertyExifColorSpace: 1]] as CFDictionary)
        guard CGImageDestinationFinalize(destination),
              let decoded = CGImageSourceCreateWithData(output, nil),
              let preview = CGImageSourceCreateImageAtIndex(decoded, 0, nil) else { throw Failure.invalid }
        return PreparedPhoto(jpeg: output as Data, raster: raster, preview: preview,
                             sourceSize: CGSize(width: width, height: height), placement: rect)
    }
}


// Serialize native decoding/rendering so rapid option changes do not multiply peak memory.
actor PhotoRenderer {
    static let shared = PhotoRenderer()
    func prepare(_ data: Data, layout: PhotoLayout, quality: Int,
                 rotation: PhotoRotation) -> Result<PreparedPhoto, Error> {
        Result {
            try Task.checkCancellation()
            return try PhotoPreparation.prepare(data, layout: layout, quality: quality, rotation: rotation)
        }
    }
}

// Read the actual JPEG SOF sampling factors; never infer sampling from quality.
enum JPEGDetails {
    static func sampling(_ data: Data) -> String {
        let b = [UInt8](data)
        guard b.count >= 4, b[0] == 255, b[1] == 216 else { return "Unknown" }
        var p = 2
        while p + 4 <= b.count {
            guard b[p] == 255 else { return "Unknown" }
            while p < b.count && b[p] == 255 { p += 1 }
            guard p < b.count else { return "Unknown" }
            let marker = b[p]; p += 1
            if marker == 218 || marker == 217 { return "Unknown" }
            if marker == 1 || (208...215).contains(marker) { continue }
            guard p + 2 <= b.count else { return "Unknown" }
            let length = Int(b[p])*256 + Int(b[p+1])
            guard length >= 2, p + length <= b.count else { return "Unknown" }
            if [UInt8(192),193,194].contains(marker) {
                guard length >= 8 else { return "Unknown" }
                let n = Int(b[p+7])
                guard length == 8 + 3*n else { return "Unknown" }
                if n == 1 { return "Grayscale" }
                guard n == 3 else { return "Unknown" }
                let factors = [b[p+9],b[p+12],b[p+15]]
                switch factors {
                case [17,17,17]: return "4:4:4 — full color resolution"
                case [33,17,17]: return "4:2:2 — reduced horizontal color resolution"
                case [34,17,17]: return "4:2:0 — reduced color resolution"
                default: return "Other sampling: " + factors.map { String(format:"%02x",$0) }.joined(separator: "/")
                }
            }
            p += length
        }
        return "Unknown"
    }
}
