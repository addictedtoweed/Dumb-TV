"""convert.py -- turn images and fonts into Dumb-TV OSD upload data.

Three converters, all producing the 4-bit palette-index pixel stream the device
uploads (index 0 = transparent):

  image_to_indices(img, W, H, palette)   # map an image onto an existing palette
  quantize_image(img, W, H, ncolors)     # derive a <=15-color palette + indices
  font_to_glyphs(font, px, W, H, chars)  # render a font into a glyph-per-char map

Needs Pillow (`pip install pillow`), imported lazily so the pure helpers in
glyphs.py stay dependency-free.

CLI:  python convert.py quantize LOGO.png 16 16    # print palette + indices
"""

import struct
import sys


def _pil():
    try:
        from PIL import Image, ImageFont, ImageDraw
        return Image, ImageFont, ImageDraw
    except ImportError:
        raise RuntimeError("Pillow not installed (pip install pillow)")


def _open(img, W, H):
    Image, _, _ = _pil()
    if isinstance(img, str):
        img = Image.open(img)
    return img.convert("RGBA").resize((W, H))


def _nearest(rgb, palette_rgb):
    """Index (1-based) of the closest palette color to rgb."""
    best, bi = 1 << 30, 1
    for i, (pr, pg, pb) in enumerate(palette_rgb):
        d = (rgb[0]-pr)**2 + (rgb[1]-pg)**2 + (rgb[2]-pb)**2
        if d < best:
            best, bi = d, i + 1        # palette entry i -> index i+1 (0 reserved)
    return bi


def image_to_indices(img, W, H, palette_rgb, alpha_thresh=128):
    """Map an image onto an existing palette (list of (r,g,b) for indices 1..N).
    Pixels below alpha_thresh become index 0 (transparent)."""
    im = _open(img, W, H)
    out = []
    for r, g, b, a in im.getdata():
        out.append(0 if a < alpha_thresh else _nearest((r, g, b), palette_rgb))
    return out


def quantize_image(img, W, H, ncolors=15, alpha_thresh=128):
    """Derive a palette (<= ncolors) from an image and return (palette, indices).
    palette is a list of (A,R,G,B) with entry 0 transparent; indices are 4-bit."""
    Image, _, _ = _pil()
    im = _open(img, W, H)
    rgb = im.convert("RGB").quantize(colors=ncolors)
    pal = rgb.getpalette()
    palette = [(0, 0, 0, 0)]           # index 0 = transparent
    for k in range(ncolors):
        r, g, b = pal[k*3:k*3+3]
        palette.append((255, r, g, b))
    alpha = list(im.getdata())
    idx = []
    for p, (r, g, b, a) in zip(rgb.getdata(), alpha):
        idx.append(0 if a < alpha_thresh else (p + 1) & 0xF)
    return palette, idx


def font_to_glyphs(font_path, px, W, H, chars=range(32, 127), thresh=128):
    """Render each char with a TrueType font into a W x H glyph (index 1 where
    inked, 0 elsewhere). Returns {char_code: indices}. Load the result as a
    contiguous font block at the device's TEXT_BASE for DRAW_TEXT."""
    Image, ImageFont, ImageDraw = _pil()
    font = ImageFont.truetype(font_path, px)
    glyphs = {}
    for c in chars:
        im = Image.new("L", (W, H), 0)
        ImageDraw.Draw(im).text((0, 0), chr(c), fill=255, font=font)
        glyphs[c] = [1 if v >= thresh else 0 for v in im.getdata()]
    return glyphs


def _emit(palette, indices):
    """Pretty-print a palette + index block as pasteable Python."""
    print("palette = [")
    for i, (a, r, g, b) in enumerate(palette):
        print(f"    ({a}, {r}, {g}, {b}),   # index {i}")
    print("]")
    print(f"indices = bytes.fromhex('{bytes(i & 0xF for i in indices).hex()}')")
    print(f"# {len(indices)} pixels")


def _main(argv):
    if len(argv) >= 4 and argv[1] == "quantize":
        path, W, H = argv[2], int(argv[3]), int(argv[4]) if len(argv) > 4 else int(argv[3])
        pal, idx = quantize_image(path, W, H)
        _emit(pal, idx)
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
