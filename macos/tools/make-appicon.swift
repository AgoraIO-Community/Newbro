import AppKit
import Foundation

// usage: swift make-appicon.swift <logo-image> <out-iconset-dir>
// <logo-image> may be webp/png/etc — anything NSImage can decode.
// If the source has no alpha channel (e.g. webp exported without transparency),
// we derive alpha from luminance (white-key) and premultiply so the white
// surround composites cleanly over the off-white squircle.
let args = CommandLine.arguments
guard args.count == 3 else {
    FileHandle.standardError.write(Data("usage: make-appicon.swift <logo-image> <iconset-dir>\n".utf8))
    exit(2)
}
guard let logoImg = NSImage(contentsOfFile: args[1]) else {
    FileHandle.standardError.write(Data("error: cannot load \(args[1])\n".utf8))
    exit(1)
}
let outDir = args[2]
let bg = NSColor(srgbRed: 0.957, green: 0.961, blue: 0.969, alpha: 1) // #f4f5f7

// If the source bitmap has no real alpha channel, derive one from luminance:
// near-white pixels become transparent, dark ink pixels stay opaque.
// Premultiply RGB so transparent pixels don't bleed their near-white color
// through when composited with sourceOver.
func makeAlphaLogo(_ img: NSImage) -> NSImage {
    guard let srcRep = img.representations.first as? NSBitmapImageRep,
          !srcRep.hasAlpha else {
        return img  // already has alpha, use as-is
    }
    let w = srcRep.pixelsWide, h = srcRep.pixelsHigh
    guard let dstRep = NSBitmapImageRep(
            bitmapDataPlanes: nil, pixelsWide: w, pixelsHigh: h,
            bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
            colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0),
          let srcPtr = srcRep.bitmapData,
          let dstPtr = dstRep.bitmapData else {
        FileHandle.standardError.write(Data("error: cannot create alpha rep\n".utf8))
        exit(1)
    }
    let srcBPR = srcRep.bytesPerRow, dstBPR = dstRep.bytesPerRow
    let srcBPP = srcRep.bitsPerPixel / 8  // bytes per pixel (may include padding)
    // Luminance threshold: pixels brighter than whiteThreshold fade to alpha 0.
    let whiteThreshold: Float = 0.97
    let fadeWidth: Float = 0.03
    for y in 0..<h {
        for x in 0..<w {
            let si = y * srcBPR + x * srcBPP
            let di = y * dstBPR + x * 4
            let r = Float(srcPtr[si])   / 255.0
            let g = Float(srcPtr[si+1]) / 255.0
            let b = Float(srcPtr[si+2]) / 255.0
            let lum = 0.299*r + 0.587*g + 0.114*b
            let alpha = max(0.0, min(1.0, (whiteThreshold - lum) / fadeWidth))
            // Premultiply: multiply RGB by alpha so transparent near-white pixels
            // don't bleed their bright color through during sourceOver compositing.
            dstPtr[di]   = UInt8(r * alpha * 255)
            dstPtr[di+1] = UInt8(g * alpha * 255)
            dstPtr[di+2] = UInt8(b * alpha * 255)
            dstPtr[di+3] = UInt8(alpha * 255)
        }
    }
    let result = NSImage(size: img.size)
    result.addRepresentation(dstRep)
    return result
}

let logo = makeAlphaLogo(logoImg)

func render(_ side: Int) -> Data {
    let size = CGFloat(side)
    guard let rep = NSBitmapImageRep(
            bitmapDataPlanes: nil, pixelsWide: side, pixelsHigh: side,
            bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
            colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0),
          let ctx = NSGraphicsContext(bitmapImageRep: rep) else {
        FileHandle.standardError.write(Data("error: cannot create context at \(side)px\n".utf8))
        exit(1)
    }
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = ctx
    // Off-white squircle filling the tile with a small transparent margin.
    let margin = size * 0.06
    let rectSide = size - margin * 2
    bg.setFill()
    NSBezierPath(roundedRect: NSRect(x: margin, y: margin, width: rectSide, height: rectSide),
                 xRadius: rectSide * 0.225, yRadius: rectSide * 0.225).fill()
    // Bro centered at ~62% of the tile. Transparent surround reveals off-white squircle.
    let logoSide = size * 0.62
    logo.draw(in: NSRect(x: (size - logoSide) / 2, y: (size - logoSide) / 2,
                         width: logoSide, height: logoSide),
              from: .zero, operation: .sourceOver, fraction: 1.0)
    NSGraphicsContext.restoreGraphicsState()
    guard let png = rep.representation(using: .png, properties: [:]) else {
        FileHandle.standardError.write(Data("error: png encode failed at \(side)px\n".utf8))
        exit(1)
    }
    return png
}

let sizes: [(String, Int)] = [
    ("icon_16x16", 16), ("icon_16x16@2x", 32),
    ("icon_32x32", 32), ("icon_32x32@2x", 64),
    ("icon_128x128", 128), ("icon_128x128@2x", 256),
    ("icon_256x256", 256), ("icon_256x256@2x", 512),
    ("icon_512x512", 512), ("icon_512x512@2x", 1024),
]

do {
    try FileManager.default.createDirectory(atPath: outDir, withIntermediateDirectories: true)
    for (name, px) in sizes {
        let path = "\(outDir)/\(name).png"
        try render(px).write(to: URL(fileURLWithPath: path))
        FileHandle.standardError.write(Data("wrote \(path)\n".utf8))
    }
} catch {
    FileHandle.standardError.write(Data("error: \(error)\n".utf8))
    exit(1)
}
