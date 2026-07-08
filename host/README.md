# Dumb-TV host tools

Host-side Python for driving the OSD over the serial protocol
(`../docs/uart-protocol.md`). All display control is these commands — no drivers,
no SDK.

| File | What |
|------|------|
| `dumbtv.py` | `DumbTV` serial client — one method per command, waits for ACK (raises on NACK). Also `frame()`/`crc8()` for building frames without serial. |
| `glyphs.py` | Boilerplate TV-op icons (input, speaker, mute, arrows, play, pause) as editable ASCII art + `art_to_indices` / `pad_center` / `upload_bytes`. Pure stdlib. |
| `convert.py` | Pillow-based converters: `image_to_indices` (onto a palette), `quantize_image` (derive a ≤15-color palette + indices, e.g. for a logo), `font_to_glyphs` (render a TTF into a glyph-per-char map). |
| `example_osd.py` | End-to-end demo: upload icons + palette, draw an input label + volume slider + text, flip. |

## Try it

```sh
# dry run — prints the exact command sequence, no hardware needed
python example_osd.py

# send it to a real device
python example_osd.py /dev/serial0

# with a font for DRAW_TEXT (loaded at TEXT_BASE=0, so char code == glyph slot)
python example_osd.py /dev/serial0 --font /usr/share/fonts/.../DejaVuSans.ttf

# turn a logo into a palette + index block you can paste
python convert.py quantize logo.png 16 16
```

Requirements: `pip install pyserial` (for the serial client) and `pillow` (for
`convert.py`). `glyphs.py` and the dry run need neither.

## Conventions

- **Glyph order is arbitrary** — you assign slots when you upload. The one
  convention: if you use `DRAW_TEXT`, load a font as a contiguous block starting
  at the firmware's `TEXT_BASE` slot, so a byte value indexes it directly (full
  **8-bit** code page). Put icons in the non-font slots.
- **Index 0 is transparent**; icons here use index 1 (recolor via palette entry
  1, or remap with `glyphs`-style helpers for multicolor).
- **Double-buffer**: draw into the back buffer, then `flip()` — the ACK returns
  after the VSync swap, so it's also your frame sync.
