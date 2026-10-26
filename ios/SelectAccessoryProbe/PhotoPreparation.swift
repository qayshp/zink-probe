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
enum PhotoPreparation {
    enum Failure: LocalizedError {
        case invalid
        var errorDescription: String? { "Cannot prepare this image. Use a single SDR JPEG, PNG or HEIC image under 50 MB and 80 megapixels." }
    }
    static func prepare(_ data: Data, layout: PhotoLayout, quality: Int) throws -> PreparedPhoto {
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
        let width = Double(image.width), height = Double(image.height)
        let inset = layout == .preserve ? 48.0 : 0
        let sx = (768 - 2 * inset) / width, sy = (1152 - 2 * inset) / height
        let scale = layout == .fill ? max(sx, sy) : min(sx, sy)
        let rect = CGRect(x: (768-width*scale)/2, y: (1152-height*scale)/2,
                          width: width*scale, height: height*scale)
        context.setFillColor(CGColor(gray: 1, alpha: 1))
        context.fill(CGRect(x: 0, y: 0, width: 768, height: 1152))
        context.interpolationQuality = .high
        context.setRenderingIntent(.relativeColorimetric)
        context.draw(image, in: rect)
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
    func prepare(_ data: Data, layout: PhotoLayout, quality: Int) -> Result<PreparedPhoto, Error> {
        Result { try PhotoPreparation.prepare(data, layout: layout, quality: quality) }
    }
}
