"""example_osd.py -- draw a small TV OSD using the glyph pack.

Demonstrates the whole toolkit: upload boilerplate icons, set a palette, then
compose a frame (input label + volume slider + speaker icon + text) using the
CLEAR -> draw -> FLIP double-buffer idiom.

Runs two ways:
  python example_osd.py                 # dry run: prints the command sequence
  python example_osd.py /dev/serial0    # send it to a real Dumb-TV

Glyph slots here (order is arbitrary -- we pick it):
  1..7   icons (input, speaker, mute, arrows, play, pause)
  32..   font, if you pass a .ttf with --font (loaded at TEXT_BASE=0, so
         char code == slot; DRAW_TEXT then just works for 8-bit code points)
"""

import sys
import glyphs
from dumbtv import DumbTV

# palette (index -> A,R,G,B); index 0 is transparent
PALETTE = {
    1: (255, 255, 255, 255),   # white   (icons, text)
    2: (255, 0, 200, 80),      # green   (slider fill)
    3: (255, 40, 40, 40),      # dark    (slider track / panel)
    4: (255, 255, 60, 60),     # red     (mute / warnings)
}

ICON_SLOTS = {                 # name -> glyph slot
    "input": 1, "speaker": 2, "mute": 3,
    "arrow_up": 4, "arrow_down": 5, "play": 6, "pause": 7,
}


def recolor(indices, frm=1, to=2):
    return [to if i == frm else i for i in indices]


def setup(tv, gw, gh, font=None):
    """Upload the palette, the icon pack, and (optionally) a font."""
    for i, (a, r, g, b) in PALETTE.items():
        tv.palette(i, a, r, g, b)
    for name, slot in ICON_SLOTS.items():
        tv.glyph_upload(slot, glyphs.upload_bytes(glyphs.icon_indices(name, gw, gh)))
    if font:
        import convert
        for code, idx in convert.font_to_glyphs(font, gh, gw, gh, range(32, 127)).items():
            tv.glyph_upload(code, glyphs.upload_bytes(idx))


def draw_osd(tv, gw, panel=(20, 20, 220, 40), volume=0.65, has_font=False):
    """Compose one OSD frame: panel, input icon, volume slider, text."""
    px, py, pw, ph = panel
    tv.clear(0)
    tv.fill_rect(px, py, pw, ph, 3)                    # panel background (dark)
    tv.glyph_blit(ICON_SLOTS["input"], px + 6, py + 6)  # input/source icon

    if has_font:
        tv.draw_text(px + 6 + gw + 4, py + 8, "HDMI 1")

    # volume slider: speaker icon + track + filled portion
    sy = py + ph + 12
    tv.glyph_blit(ICON_SLOTS["speaker"], px, sy - 4)
    track_x, track_w = px + gw + 4, pw - gw - 4
    tv.fill_rect(track_x, sy, track_w, 6, 3)                       # track
    tv.fill_rect(track_x, sy, int(track_w * volume), 6, 2)        # fill (green)

    tv.enable(True)
    tv.flip()                                          # show it (swaps at VSync)


# ---- dry-run transport: records/prints commands instead of using serial ----
class _Recorder:
    def __init__(self):
        self.n = 0

    def __getattr__(self, name):
        def rec(*args):
            self.n += 1
            shown = ", ".join(str(a) if not isinstance(a, (bytes, bytearray))
                              else f"<{len(a)}B>" for a in args)
            print(f"{self.n:3}: {name}({shown})")
        return rec


def main(argv):
    port = argv[1] if len(argv) > 1 and not argv[1].startswith("--") else None
    font = None
    if "--font" in argv:
        font = argv[argv.index("--font") + 1]

    if port:
        tv = DumbTV(port)
        nfo = tv.info()
        gw = gh = 16                       # real device glyph cell (from your build)
        print("connected:", nfo)
    else:
        tv = _Recorder()
        gw = gh = 16
        print("# dry run -- command sequence:")

    setup(tv, gw, gh, font=font)
    draw_osd(tv, gw, volume=0.65, has_font=bool(font))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
