# Dumb-TV UART control protocol

This is the serial command interface between a host (your Raspberry Pi / Linux
box) and the Dumb-TV FPGA. With it you can:

- turn the on-screen overlay on/off, move/resize it, fade it
- **upload custom overlay graphics** into the OSD framebuffer
- (reserved) adjust picture controls like brightness/contrast

It is a small **binary framed** protocol — deliberately tiny so it's quick to
implement and robust enough to stream image data. A complete, copy-pasteable
Python implementation is at the bottom.

---

## 1. Physical link

| Setting   | Value                                             |
|-----------|---------------------------------------------------|
| Levels    | 3.3 V TTL UART (do **not** connect RS-232 levels) |
| Default baud | 115200                                         |
| Fast baud | up to 1000000 (recommended for image uploads)     |
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

- `0xA5` — start-of-frame sync byte. If the parser is mid-resync it discards
  bytes until it sees this.
- `CMD` — command/response opcode (tables below).
- `LEN` — number of payload bytes (0..65535), little-endian.
- `PAYLOAD` — `LEN` bytes.
- `CRC8` — checksum over **CMD, LEN_LO, LEN_HI and PAYLOAD** (not the sync byte).
  Polynomial `0x07`, init `0x00` (CRC-8/SMBUS). 8-line implementation below.

If a frame fails CRC or has an unknown opcode, the device replies `NACK`.

---

## 3. Commands (host → device)

| Opcode | Name           | Payload                                  |
|--------|----------------|------------------------------------------|
| `0x01` | PING           | (none) → device replies `ACK`            |
| `0x02` | GET_INFO       | (none) → device replies `INFO`           |
| `0x10` | OSD_ENABLE     | `en`(1): 0=off, 1=on                      |
| `0x11` | OSD_WINDOW     | `x0`(2) `y0`(2) `w`(2) `h`(2)             |
| `0x12` | OSD_ALPHA      | `alpha`(1): 0=transparent .. 255=full     |
| `0x20` | OSD_FB_WRITE   | `addr`(2) then N×`{A,R,G,B}` texels       |
| `0x21` | OSD_FB_FILL    | `addr`(2) `count`(2) `A`(1)`R`(1)`G`(1)`B`(1) |
| `0x30` | BRIGHTNESS *(reserved)* | `level`(1)                      |
| `0x31` | CONTRAST *(reserved)*   | `level`(1)                      |

### Field meanings

- **OSD_WINDOW** places the overlay on screen: `(x0,y0)` is the top-left pixel
  on the output, `(w,h)` how many framebuffer texels to show. `w`/`h` must be
  ≤ the framebuffer size reported by `GET_INFO`.
- **OSD_ALPHA** is a *master fade* multiplied with each texel's own alpha, so
  you can fade the whole overlay in/out without re-uploading it.
- **OSD_FB_WRITE / OSD_FB_FILL** write into the OSD framebuffer (see §5).

---

## 4. Responses (device → host)

| Opcode | Name | Payload                                                       |
|--------|------|--------------------------------------------------------------|
| `0x80` | ACK  | `cmd`(1) — the command being acknowledged                    |
| `0x81` | NACK | `cmd`(1) `err`(1)                                            |
| `0x82` | INFO | `proto`(1) `fw_major`(1) `fw_minor`(1) `osd_w`(2) `osd_h`(2) `max_w`(2) `max_h`(2) `flags`(1) |

Error codes (`NACK.err`): `0x01` bad CRC, `0x02` bad length, `0x03` unknown
command, `0x04` value/address out of range, `0x05` busy.

The device sends an `ACK` (or `NACK`) for **every** command. Wait for it before
sending the next frame — that's your flow control, and it matters when streaming
an upload so you don't overrun the receive buffer.

`INFO.osd_w`/`osd_h` are the framebuffer dimensions (powers of two). Read these
at startup instead of hard-coding — they will grow as the product evolves
(the simulation scaffold ships tiny, e.g. 8×4).

---

## 5. Uploading overlay graphics

The OSD framebuffer is `osd_w × osd_h` texels. Each texel is **4 bytes in
`A, R, G, B` order** (alpha first). Texels are linearly addressed:

```
    addr = y * osd_w + x          # x = column 0..osd_w-1, y = row 0..osd_h-1
```

To upload an image:

1. `GET_INFO` → learn `osd_w`, `osd_h`.
2. Render/resize your overlay to exactly `osd_w × osd_h`, RGBA.
3. Send it with one or more `OSD_FB_WRITE` frames. `addr` is the first texel;
   the payload then carries consecutive texels. **Chunk** large images into
   several frames (e.g. 256 texels per frame) and wait for each `ACK` — this
   keeps frames small and flow-controlled.
4. `OSD_WINDOW` to position it, `OSD_ALPHA 255`, `OSD_ENABLE 1`.

Alpha is per-texel: `A=0` is fully transparent (video shows through), `A=255`
fully opaque. That's how you get non-rectangular logos/text — make the
background texels transparent.

`OSD_FB_FILL` writes the same texel `count` times starting at `addr` — handy to
clear the framebuffer (`fill addr=0 count=osd_w*osd_h A=0`) before drawing.

### Latency note

OSD updates are intentionally allowed to be slow; the live video path is not
affected by uploads. Upload whenever you like — even mid-frame — and the change
appears on the next frames. The video itself passes through at full speed.

---

## 6. Reference implementation (Python + pyserial)

```python
import struct, serial
from PIL import Image          # pip install pyserial pillow

SYNC = 0xA5

# --- CRC-8/SMBUS (poly 0x07, init 0x00) ---
def crc8(data: bytes) -> int:
    c = 0
    for byte in data:
        c ^= byte
        for _ in range(8):
            c = ((c << 1) ^ 0x07) & 0xFF if (c & 0x80) else (c << 1) & 0xFF
    return c

class DumbTV:
    def __init__(self, port="/dev/serial0", baud=115200):
        self.s = serial.Serial(port, baud, timeout=1.0)

    def _send(self, cmd: int, payload: bytes = b"") -> None:
        body = bytes([cmd]) + struct.pack("<H", len(payload)) + payload
        self.s.write(bytes([SYNC]) + body + bytes([crc8(body)]))

    def _read_frame(self):
        # find sync
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

    def _cmd(self, cmd: int, payload: bytes = b""):
        self._send(cmd, payload)
        rcmd, rpl = self._read_frame()
        if rcmd == 0x81:                       # NACK
            raise IOError(f"NACK cmd=0x{rpl[0]:02x} err=0x{rpl[1]:02x}")
        return rcmd, rpl

    # --- high-level API ---
    def info(self):
        _, p = self._cmd(0x02)
        proto, fwma, fwmi, ow, oh, mw, mh, flags = struct.unpack("<BBBHHHHB", p)
        return dict(proto=proto, fw=(fwma, fwmi), osd_w=ow, osd_h=oh,
                    max_w=mw, max_h=mh, flags=flags)

    def enable(self, on):        self._cmd(0x10, bytes([1 if on else 0]))
    def window(self, x0, y0, w, h):
        self._cmd(0x11, struct.pack("<HHHH", x0, y0, w, h))
    def alpha(self, a):          self._cmd(0x12, bytes([a]))

    def fill(self, addr, count, a, r, g, b):
        self._cmd(0x21, struct.pack("<HH", addr, count) + bytes([a, r, g, b]))

    def upload_image(self, path, osd_w, osd_h, chunk=256):
        img = Image.open(path).convert("RGBA").resize((osd_w, osd_h))
        # build A,R,G,B texel stream
        texels = bytearray()
        for r, g, b, a in img.getdata():
            texels += bytes([a, r, g, b])
        for i in range(0, osd_w * osd_h, chunk):
            addr = i
            data = texels[i*4:(i+chunk)*4]
            self._cmd(0x20, struct.pack("<H", addr) + data)

# --- example session ---
tv = DumbTV("/dev/serial0", 115200)
nfo = tv.info()
print("framebuffer:", nfo["osd_w"], "x", nfo["osd_h"])
tv.fill(0, nfo["osd_w"] * nfo["osd_h"], 0, 0, 0, 0)   # clear (transparent)
tv.upload_image("logo.png", nfo["osd_w"], nfo["osd_h"])
tv.window(x0=32, y0=32, w=nfo["osd_w"], h=nfo["osd_h"])
tv.alpha(255)
tv.enable(True)
```

---

## 7. Quick reference card

```
FRAME:  A5 | CMD | LEN_LO LEN_HI | PAYLOAD... | CRC8(CMD..PAYLOAD)
INT:    little-endian      TEXEL: A R G B (4B)     ADDR: y*osd_w + x

0x01 PING            -> ACK
0x02 GET_INFO        -> INFO(proto,fw,osd_w,osd_h,max_w,max_h,flags)
0x10 OSD_ENABLE  en
0x11 OSD_WINDOW  x0 y0 w h
0x12 OSD_ALPHA   a
0x20 OSD_FB_WRITE addr texels...
0x21 OSD_FB_FILL  addr count A R G B

0x80 ACK  cmd          0x81 NACK cmd err          0x82 INFO ...
err: 01 crc  02 len  03 unknown  04 range  05 busy
```

*This document is the external contract. Internally the FPGA's UART parser maps
these commands onto the `ctrl_regs` register writes and the `osd_fb` framebuffer
write port described in the RTL — see `rtl/`.*
