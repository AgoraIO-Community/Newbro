import AppKit
import Foundation

// usage: swift make-appicon.swift <logo.png> <out-iconset-dir>
let args = CommandLine.arguments
guard args.count == 3 else {
    FileHandle.standardError.write(Data("usage: make-appicon.swift <logo.png> <iconset-dir>\n".utf8))
    exit(2)
}
let logoPath = args[1]
let outDir = args[2]

guard let logo = NSImage(contentsOfFile: logoPath) else {
    FileHandle.standardError.write(Data("error: cannot load \(logoPath)\n".utf8))
    exit(1)
}

let bg = NSColor(srgbRed: 0.957, green: 0.961, blue: 0.969, alpha: 1) // #f4f5f7

func render(_ side: Int) -> Data {
    let size = CGFloat(side)
    let img = NSImage(size: NSSize(width: size, height: size))
    img.lockFocus()
    // Off-white squircle filling the tile with a small transparent margin.
    let margin = size * 0.06
    let rectSide = size - margin * 2
    let bgRect = NSRect(x: margin, y: margin, width: rectSide, height: rectSide)
    let radius = rectSide * 0.225
    bg.setFill()
    NSBezierPath(roundedRect: bgRect, xRadius: radius, yRadius: radius).fill()
    // Bro centered at ~62% of the tile.
    let logoSide = size * 0.62
    let logoRect = NSRect(x: (size - logoSide) / 2, y: (size - logoSide) / 2,
                          width: logoSide, height: logoSide)
    logo.draw(in: logoRect, from: .zero, operation: .sourceOver, fraction: 1.0)
    img.unlockFocus()
    guard let tiff = img.tiffRepresentation,
          let rep = NSBitmapImageRep(data: tiff),
          let png = rep.representation(using: .png, properties: [:]) else {
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
