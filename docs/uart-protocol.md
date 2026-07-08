# Dumb-TV UART control protocol

Serial command interface between a host (Raspberry Pi / Linux box) and the
Dumb-TV FPGA. With it you can:

- turn the on-screen overlay on/off and fade it
- set the 16-color **palette**
- **upload the overlay** as 4-bit palette indices into the OSD canvas
- **double-buffer** it (`CLEAR` / `FLIP`) for flicker-free, tear-free updates
- (planned) blit glyphs / text / rectangles — see §7

The OSD is a **full-screen indexed plane**: a low-resolution canvas of 4-bit
palette indices that the FPGA stretches (nearest-neighbour) to the whole active
picture. Index 0 is transparent, so wherever you don't draw, the video shows
through — the overlay is borderless, not a box.

It is a small **binary framed** protocol. A copy-pasteable Python implementation
is at the bottom.

---

## 1. Physical link

| Setting   | Value                                             |
|-----------|---------------------------------------------------|
| Levels    | 3.3 V TTL UART (do **not** connect RS-232 levels) |
| Default baud | 115200                                         |
| Fast baud | up to 1000000 (recommended for bulk uploads)      |
| Format    | 8 data bits, no parity, 1 stop bit (8N1)          |
| Flow ctrl | none (software ACK, see below)                    |
| Pins      | TX, RX, GND. Cross TX↔RX. (Pi GPIO14/15 = `/dev/serial0`) |

All multi-byte integers are **little-endian**.

---

## 2. Frame format

Every message in both directions is one frame:

```
 +------+------+--------+--------+===============+------+
 | 0xA5 | CMD  | LEN_LO | LEN_HI |   PAYLOAD ... | CRC8 |
 +------+------+--------+--------+===============+------+
   sync   1B      16-bit LE         LEN bytes      1B
```

- `0xA5` — start-of-frame sync byte; the parser resyncs by discarding bytes
  until it sees one.
- `CMD` — command/response opcode (tables below).
- `LEN` — payload length in bytes (0..65535), little-endian.
- `CRC8` — over **CMD, LEN_LO, LEN_HI and PAYLOAD** (not the sync byte).
  Polynomial `0x07`, init `0x00` (CRC-8/SMBUS). 8-line implementation below.

A frame that fails CRC, has a bad length, an unknown opcode, or an out-of-range
address gets a `NACK` with the reason code.

---

## 3. Commands (host → device)

| Opcode | Name         | Payload                                               |
|--------|--------------|-------------------------------------------------------|
| `0x01` | PING         | (none) → `ACK`                                        |
| `0x02` | GET_INFO     | (none) → `INFO`                                       |
| `0x10` | OSD_ENABLE   | `en`(1): 0=off, 1=on                                  |
| `0x12` | OSD_ALPHA    | `alpha`(1): master fade, 0=off .. 255=full            |
| `0x20` | OSD_FB_WRITE | `addr`(2) + N `index` bytes (low nibble = 4-bit index)|
| `0x26` | PALETTE_SET  | `index`(1) `A`(1) `R`(1) `G`(1) `B`(1)                |
| `0x21` | OSD_FB_FILL  | `addr`(2) `count`(2) `index`(1)                       |
| `0x22` | GLYPH_UPLOAD | `slot`(1) + `GW*GH` index bytes (one 4-bit px/byte)   |
| `0x23` | GLYPH_BLIT   | `slot`(1) `x`(2) `y`(2) — draw glyph at canvas (x,y)   |
| `0x24` | DRAW_TEXT    | `x`(2) `y`(2) + string bytes (slot = TEXT_BASE + char)|
| `0x25` | FILL_RECT    | `x`(2) `y`(2) `w`(2) `h`(2) `index`(1)                |
| `0x27` | CLEAR        | *(optional `index`(1); default 0)* — wipe back buffer |
| `0x28` | FLIP         | *(none)* — swap buffers at VSync; ACK **after** swap  |
| `0x30` | BRIGHTNESS    | `level`(1) — picture brightness, 128 = neutral      |
| `0x31` | CONTRAST      | `level`(1) — picture contrast, 128 = unity gain     |
| `0x32` | BACKLIGHT     | `duty`(1) — backlight PWM, 0 = off .. 255 = full    |
| `0x40` | INPUT_SELECT  | `sel`(1) — set the input mux select (0..15)         |

### Field meanings

- **OSD_ENABLE** gates the whole overlay. **OSD_ALPHA** is a master fade
  multiplied with each pixel's palette alpha — fade the overlay in/out without
  re-uploading.
- **PALETTE_SET** sets one of the 16 palette entries to a color + alpha. By
  convention **index 0 is transparent** (leave it, or set its alpha to 0), so
  entries 1..15 are your usable colors.
- **OSD_FB_WRITE** streams canvas pixels as 4-bit palette indices, one index per
  byte (low nibble), starting at linear `addr`. **OSD_FB_FILL** writes the same
  index `count` times — handy to clear (`fill addr=0 count=osd_w*osd_h index=0`).

There is no window/position command: the canvas always covers the full screen,
stretched. Position elements by where you draw them in the canvas.

---

## 4. Responses (device → host)

| Opcode | Name | Payload                                                       |
|--------|------|--------------------------------------------------------------|
| `0x80` | ACK  | `cmd`(1) — the command acknowledged                          |
| `0x81` | NACK | `cmd`(1) `err`(1)                                            |
| `0x82` | INFO | `proto`(1) `fw_major`(1) `fw_minor`(1) `osd_w`(2) `osd_h`(2) `max_w`(2) `max_h`(2) `flags`(1) |

Error codes (`NACK.err`): `0x01` bad CRC, `0x02` bad length, `0x03` unknown
command, `0x04` address out of range.

The device sends `ACK`/`NACK` for **every** command — wait for it before sending
the next frame. That's your flow control (and, for streaming uploads, what keeps
you from overrunning the receive buffer).

`INFO.osd_w`/`osd_h` are the **canvas** dimensions (the low-res plane, e.g.
640×360 on hardware, 8×4 in the sim scaffold). Read them at startup rather than
hard-coding — they can change per build. `max_w`/`max_h` are the target display
size (1920×1080).

---

## 5. Drawing the overlay

The canvas is `osd_w × osd_h` **4-bit palette indices**, addressed linearly:

```
    addr = y * osd_w + x        # x = 0..osd_w-1, y = 0..osd_h-1
```

Typical sequence:

1. `GET_INFO` → learn `osd_w`, `osd_h`.
2. `PALETTE_SET` for each color you use (index 1..15; index 0 = transparent).
3. `OSD_FB_WRITE` the index map (chunk large canvases into several frames, wait
   for each `ACK`).
4. `OSD_ALPHA 255`, `OSD_ENABLE 1`.

Because the plane is transparent wherever an index is 0, elements can sit
anywhere on screen with no surrounding box; the video shows through everywhere
else.

### Double buffering — flicker-free redraw

The canvas is **double-buffered**. All drawing (`OSD_FB_WRITE`, `OSD_FB_FILL`,
`CLEAR`) goes to the hidden **back** buffer; the screen shows the **front**
buffer. `FLIP` swaps them at the next VSync (no tearing), so a redraw only ever
appears whole. The idiom:

```
CLEAR                 # wipe the back buffer
... draw ...          # OSD_FB_WRITE / OSD_FB_FILL (and, later, glyph blits)
FLIP                  # swap; the ACK arrives only after the swap completes
```

`FLIP`'s ACK is your frame sync point: it returns *after* the buffers have
swapped, so the buffer you just released is safe to draw into next. (It's also a
free ~60 Hz heartbeat.) A frame with a bad CRC mid-upload simply never gets
flipped, so corruption is never shown.

### Glyphs and rectangles

Instead of re-uploading pixels, build the OSD from reusable pieces:

- **`GLYPH_UPLOAD`** stores a small glyph (icon, arrow, character) into one of
  the glyph slots — `GW × GH` 4-bit indices, one pixel per byte, row-major.
  Upload each glyph once; `GET_INFO` reports the glyph size and slot count.
- **`GLYPH_BLIT`** stamps glyph `slot` into the back buffer at canvas `(x, y)`.
  Glyph pixels with index 0 are transparent (skipped), so non-rectangular shapes
  compose cleanly. Off-canvas pixels are clipped. Blit the same glyph as many
  times as you like — a blit is ~6 bytes.
- **`FILL_RECT`** fills a rectangle with one palette index — bars, backgrounds,
  underlines, progress meters.

- **`DRAW_TEXT`** blits a whole string in one command: for each byte `c` it
  blits glyph slot `TEXT_BASE + c` at advancing x. Load a **font** as a
  contiguous block of glyphs starting at slot `TEXT_BASE` (the firmware default
  is 0), and the byte values you send index it directly — full **8-bit** range
  (a 256-glyph code page), not just 7-bit ASCII. Reserve the non-font slots for
  icons.

All of these draw into the **back** buffer, so the flow stays `CLEAR` → glyphs /
text / rects / writes → `FLIP`.

## Input mux — `INPUT_SELECT`

`INPUT_SELECT sel` sets a small `mux_sel` register exposed as FPGA output pins.
Use it to switch an external DP/HDMI mux, or to select between multiple RGB
deserializers feeding the FPGA. It's just another serial command, so input
switching is scriptable like everything else.

### Latency note

OSD updates are decoupled from the live video: the picture passes through at
full speed regardless of when you draw or flip.

---

## 6. Reference implementation (Python + pyserial)

```python
import struct, serial
from PIL import Image          # pip install pyserial pillow

SYNC = 0xA5

def crc8(data: bytes) -> int:                       # CRC-8/SMBUS, poly 0x07
    c = 0
    for byte in data:
        c ^= byte
        for _ in range(8):
            c = ((c << 1) ^ 0x07) & 0xFF if (c & 0x80) else (c << 1) & 0xFF
    return c

class DumbTV:
    def __init__(self, port="/dev/serial0", baud=115200):
        self.s = serial.Serial(port, baud, timeout=1.0)

    def _send(self, cmd, payload=b""):
        body = bytes([cmd]) + struct.pack("<H", len(payload)) + payload
        self.s.write(bytes([SYNC]) + body + bytes([crc8(body)]))

    def _read_frame(self):
        while True:
            b = self.s.read(1)
            if not b:
                raise TimeoutError("no response")
            if b[0] == SYNC:
                break
        hdr = self.s.read(3)
        cmd, length = hdr[0], hdr[1] | (hdr[2] << 8)
        payload = self.s.read(length)
        crc = self.s.read(1)[0]
        if crc != crc8(hdr + payload):
            raise IOError("bad CRC in response")
        return cmd, payload

    def _cmd(self, cmd, payload=b""):
        self._send(cmd, payload)
        rcmd, rpl = self._read_frame()
        if rcmd == 0x81:                            # NACK
            raise IOError(f"NACK cmd=0x{rpl[0]:02x} err=0x{rpl[1]:02x}")
        return rcmd, rpl

    # --- high-level API ---
    def info(self):
        _, p = self._cmd(0x02)
        proto, fwma, fwmi, ow, oh, mw, mh, flags = struct.unpack("<BBBHHHHB", p)
        return dict(proto=proto, fw=(fwma, fwmi), osd_w=ow, osd_h=oh,
                    max_w=mw, max_h=mh, flags=flags)

    def enable(self, on):     self._cmd(0x10, bytes([1 if on else 0]))
    def alpha(self, a):       self._cmd(0x12, bytes([a]))
    def palette(self, i, a, r, g, b):
        self._cmd(0x26, bytes([i, a, r, g, b]))
    def fill(self, addr, count, index):
        self._cmd(0x21, struct.pack("<HH", addr, count) + bytes([index]))
    def clear(self, index=0):  self._cmd(0x27, bytes([index]))
    def flip(self):            self._cmd(0x28)   # returns after the VSync swap
    def glyph_upload(self, slot, pixels):        # pixels: bytes of 4-bit indices
        self._cmd(0x22, bytes([slot]) + bytes(pixels))
    def glyph_blit(self, slot, x, y):
        self._cmd(0x23, bytes([slot]) + struct.pack("<HH", x, y))
    def draw_text(self, x, y, s):                # s: bytes / str (8-bit chars)
        b = s.encode("latin-1") if isinstance(s, str) else bytes(s)
        self._cmd(0x24, struct.pack("<HH", x, y) + b)
    def fill_rect(self, x, y, w, h, index):
        self._cmd(0x25, struct.pack("<HHHH", x, y, w, h) + bytes([index]))
    def input_select(self, sel):
        self._cmd(0x40, bytes([sel]))
    def brightness(self, level):   self._cmd(0x30, bytes([level]))   # 128 = neutral
    def contrast(self, level):     self._cmd(0x31, bytes([level]))   # 128 = unity
    def backlight(self, duty):     self._cmd(0x32, bytes([duty]))    # 0..255 PWM

    def write_indices(self, indices, addr=0, chunk=512):
        for i in range(0, len(indices), chunk):
            self._cmd(0x20, struct.pack("<H", addr + i) + bytes(indices[i:i+chunk]))

    def upload_image(self, path, osd_w, osd_h):
        # quantize to <=15 colors, keep index 0 transparent
        img = Image.open(path).convert("RGB").resize((osd_w, osd_h)).quantize(colors=15)
        pal = img.getpalette()                      # [r,g,b, r,g,b, ...]
        self.palette(0, 0, 0, 0, 0)                 # index 0 = transparent
        for k in range(15):
            r, g, b = pal[k*3:k*3+3]
            self.palette(k + 1, 255, r, g, b)       # entries 1..15 opaque
        idx = bytes((p + 1) for p in img.getdata()) # shift 0..14 -> 1..15
        self.write_indices(idx, 0)

# --- example session ---
tv = DumbTV("/dev/serial0", 115200)
nfo = tv.info()
print("canvas:", nfo["osd_w"], "x", nfo["osd_h"])
tv.clear(0)                                         # wipe the back buffer
tv.upload_image("logo.png", nfo["osd_w"], nfo["osd_h"])  # draw into back buffer
tv.alpha(255)
tv.enable(True)
tv.flip()                                           # show it (swaps at VSync)
```

---

## 7. Planned (stage 2) — not yet implemented

The full command set is implemented — OSD, double-buffering, glyphs/text/rects,
picture controls, backlight, and the input mux. `BRIGHTNESS`/`CONTRAST` apply a
pixel-math stage to the **video** before the OSD is blended on top (so menus stay
a fixed brightness): `out = clamp((v - 128) * contrast / 128 + brightness)`,
neutral at `brightness = 128, contrast = 128`.

`BACKLIGHT` sets an 8-bit PWM duty on the `backlight` output pin — drive a CCFL
inverter's dimming input or an LED-driver PWM/EN. Defaults to full on so the
panel is lit out of the box.

---

## 8. Quick reference card

```
FRAME:  A5 | CMD | LEN_LO LEN_HI | PAYLOAD... | CRC8(CMD..PAYLOAD)
INT: little-endian    PIXEL: 4-bit palette index    ADDR: y*osd_w + x

0x01 PING            -> ACK
0x02 GET_INFO        -> INFO(proto,fw,osd_w,osd_h,max_w,max_h,flags)
0x10 OSD_ENABLE  en
0x12 OSD_ALPHA   a
0x26 PALETTE_SET index A R G B      (index 0 = transparent)
0x20 OSD_FB_WRITE addr indices...   (one 4-bit index per byte)   -> back buffer
0x21 OSD_FB_FILL  addr count index                               -> back buffer
0x22 GLYPH_UPLOAD slot pixels...    (GW*GH indices, one per byte)
0x23 GLYPH_BLIT   slot x y                                       -> back buffer
0x24 DRAW_TEXT    x y bytes...      (slot = TEXT_BASE + char)     -> back buffer
0x25 FILL_RECT    x y w h index                                  -> back buffer
0x27 CLEAR        [index]           (wipe back buffer)
0x28 FLIP                           (swap at VSync; ACK after swap)
0x30 BRIGHTNESS   level             (128 = neutral)
0x31 CONTRAST     level             (128 = unity)
0x32 BACKLIGHT    duty              (0=off .. 255=full)
0x40 INPUT_SELECT sel               (set input mux 0..15)

0x80 ACK cmd     0x81 NACK cmd err     0x82 INFO ...
err: 01 crc  02 len  03 unknown  04 range
```

*External contract. Internally the parser maps these onto `ctrl_regs`, the
`osd_fb` canvas write port (4-bit indices), and the `palette` write port — see
`rtl/`. The canvas lives in BRAM or external PSRAM depending on the build
(`CANVAS=bram|psram`), transparently to this protocol.*
