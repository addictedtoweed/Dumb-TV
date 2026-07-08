"""glyphs.py -- boilerplate OSD glyph pack + art-to-indices conversion.

Glyphs are authored as ASCII art (easy to read and edit) and converted to the
4-bit palette-index pixel stream the device wants. `.`/space = transparent
(index 0); `#` = index 1 (so an icon is one color, recolored by whatever you put
in palette entry 1); digits `1`-`9` and `a`-`f` give indices 1..15 for
multi-color glyphs.

Glyph *order does not matter* -- you assign slots when you upload. (The one
convention: if you use DRAW_TEXT, load your font as a contiguous block starting
at the firmware's TEXT_BASE slot, so byte value == font slot.)

These icons are 8x8 starters; `pad_center` fits them into the device's glyph
cell (e.g. 16x16). Customize freely.
"""

# name -> ASCII art (all rows equal length)
ICONS = {
    "arrow_up": [
        "   ##   ",
        "  ####  ",
        " ###### ",
        "########",
        "  ####  ",
        "  ####  ",
        "  ####  ",
        "        ",
    ],
    "arrow_down": [
        "        ",
        "  ####  ",
        "  ####  ",
        "  ####  ",
        "########",
        " ###### ",
        "  ####  ",
        "   ##   ",
    ],
    "speaker": [
        "   ##   ",
        "  ###  #",
        " #### # ",
        "##### ##",
        "##### ##",
        " #### # ",
        "  ###  #",
        "   ##   ",
    ],
    "mute": [
        "   ##   ",
        "  ###  #",
        " #### # ",
        "##### # ",
        "##### # ",
        " #### # ",
        "  ###  #",
        "   ##   ",
    ],
    "input": [          # monitor with a stand -- "source / input"
        "########",
        "#      #",
        "#      #",
        "#      #",
        "########",
        "   ##   ",
        "  ####  ",
        "        ",
    ],
    "play": [
        "        ",
        " ##     ",
        " ####   ",
        " ###### ",
        " ###### ",
        " ####   ",
        " ##     ",
        "        ",
    ],
    "pause": [
        "        ",
        " ## ##  ",
        " ## ##  ",
        " ## ##  ",
        " ## ##  ",
        " ## ##  ",
        " ## ##  ",
        "        ",
    ],
}


def _default_charmap():
    cm = {".": 0, " ": 0, "#": 1}
    for i, c in enumerate("0123456789abcdef"):
        cm[c] = i
    return cm


def art_to_indices(rows, charmap=None):
    """Convert ASCII-art rows to (w, h, indices) with indices row-major."""
    cm = charmap or _default_charmap()
    w = len(rows[0])
    assert all(len(r) == w for r in rows), "art rows must be equal length"
    idx = [cm.get(ch, 0) & 0xF for r in rows for ch in r]
    return w, len(rows), idx


def pad_center(w, h, idx, W, H, fill=0):
    """Center a w x h glyph into a W x H cell (transparent padding)."""
    ox, oy = (W - w) // 2, (H - h) // 2
    out = [fill] * (W * H)
    for y in range(h):
        for x in range(w):
            X, Y = ox + x, oy + y
            if 0 <= X < W and 0 <= Y < H:
                out[Y * W + X] = idx[y * w + x]
    return out


def icon_indices(name, W, H):
    """Boilerplate icon, padded/centered to the device glyph cell (W x H)."""
    w, h, idx = art_to_indices(ICONS[name])
    return pad_center(w, h, idx, W, H)


def upload_bytes(indices):
    """The GLYPH_UPLOAD pixel payload: one 4-bit index per byte."""
    return bytes(i & 0xF for i in indices)
