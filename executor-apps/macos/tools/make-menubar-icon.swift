import AppKit
import Foundation

// usage: swift make-menubar-icon.swift <logo-image> <out.png>
// Produces a black-on-transparent silhouette of the bro, tightly cropped, for use
// as a menu bar TEMPLATE image (the app tints it black/white to match the bar).
// The source logo is opaque two-tone (dark ink on near-white); we white-key it so
// the dark linework stays and the light face/background become transparent.
let args = CommandLine.arguments
guard args.count == 3 else {
    FileHandle.standardError.write(Data("usage: make-menubar-icon.swift <logo-image> <out.png>\n".utf8))
    exit(2)
}
guard let img = NSImage(contentsOfFile: args[0 + 1]),
      let src = img.representations.first as? NSBitmapImageRep,
      let sp = src.bitmapData else {
    FileHandle.standardError.write(Data("error: cannot load \(args[1])\n".utf8))
    exit(1)
}
let outPath = args[2]

let w = src.pixelsWide, h = src.pixelsHigh
let bpr = src.bytesPerRow, bpp = src.bitsPerPixel / 8

// White-key: dark ink -> opaque (alpha 1), near-white -> transparent (alpha 0).
func key(_ x: Int, _ y: Int) -> Float {
    let i = y * bpr + x * bpp
    let r = Float(sp[i]) / 255, g = Float(sp[i + 1]) / 255, b = Float(sp[i + 2]) / 255
    let lum = 0.299 * r + 0.587 * g + 0.114 * b
    return max(0, min(1, (0.97 - lum) / 0.03))
}

var a = [Float](repeating: 0, count: w * h)
var col = [Int](repeating: 0, count: w), row = [Int](repeating: 0, count: h)
for y in 0..<h {
    for x in 0..<w {
        let av = key(x, y)
        a[y * w + x] = av
        if av > 0.9 { col[x] += 1; row[y] += 1 }  // count only solid ink
    }
}

// Tight bbox: first/last column & row holding a meaningful run of solid ink,
// which ignores the faint compression noise scattered across the background.
let minRun = h / 25
var minx = 0; while minx < w && col[minx] < minRun { minx += 1 }
var maxx = w - 1; while maxx > 0 && col[maxx] < minRun { maxx -= 1 }
var miny = 0; while miny < h && row[miny] < minRun { miny += 1 }
var maxy = h - 1; while maxy > 0 && row[maxy] < minRun { maxy -= 1 }
guard maxx > minx, maxy > miny else {
    FileHandle.standardError.write(Data("error: could not locate bro silhouette\n".utf8))
    exit(1)
}

let cw = maxx - minx + 1, ch = maxy - miny + 1
let pad = Int(Double(max(cw, ch)) * 0.10)
let side = max(cw, ch) + pad * 2
let cx = (minx + maxx) / 2, cy = (miny + maxy) / 2
let sx0 = cx - side / 2, sy0 = cy - side / 2

let target = 144
let scale = Double(target) / Double(side)
let osz = Int(Double(side) * scale)
guard let out = NSBitmapImageRep(
        bitmapDataPlanes: nil, pixelsWide: osz, pixelsHigh: osz,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0),
      let op = out.bitmapData else {
    FileHandle.standardError.write(Data("error: cannot create output rep\n".utf8))
    exit(1)
}
let obpr = out.bytesPerRow
for oy in 0..<osz {
    for ox in 0..<osz {
        let sx = sx0 + Int(Double(ox) / scale), sy = sy0 + Int(Double(oy) / scale)
        var av: Float = 0
        if sx >= 0, sx < w, sy >= 0, sy < h { av = a[sy * w + sx] }
        if av < 0.5 { av = 0 }  // drop faint noise; keep solid ink + crisp edges
        let di = oy * obpr + ox * 4
        op[di] = 0; op[di + 1] = 0; op[di + 2] = 0; op[di + 3] = UInt8(av * 255)
    }
}

do {
    try out.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: outPath))
    FileHandle.standardError.write(Data("wrote \(outPath) (\(osz)x\(osz), bro \(cw)x\(ch))\n".utf8))
} catch {
    FileHandle.standardError.write(Data("error: \(error)\n".utf8))
    exit(1)
}
