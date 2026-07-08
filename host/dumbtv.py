"""dumbtv.py -- host-side client for the Dumb-TV UART OSD protocol.

A thin, dependency-free (stdlib + pyserial) wrapper over the framed serial
protocol in docs/uart-protocol.md. Every method sends one command and waits for
its ACK; a NACK raises.

    tv = DumbTV("/dev/serial0", 115200)
    info = tv.info()
    tv.palette(1, 255, 255, 255, 255)     # index 1 = opaque white
    tv.clear(0)
    tv.draw_text(8, 8, "HELLO")
    tv.flip()
"""

import struct

try:
    import serial  # pyserial
except ImportError:      # allow importing the class/helpers without pyserial
    serial = None

SYNC = 0xA5

# opcodes
OP_PING, OP_INFO = 0x01, 0x02
OP_EN, OP_ALPHA = 0x10, 0x12
OP_FBW, OP_FBF, OP_PAL = 0x20, 0x21, 0x26
OP_GUP, OP_GBLIT, OP_TEXT, OP_FRECT = 0x22, 0x23, 0x24, 0x25
OP_CLEAR, OP_FLIP, OP_MUXSEL = 0x27, 0x28, 0x40
OP_BRIGHT, OP_CONTR, OP_BL = 0x30, 0x31, 0x32
OP_FWHALT, OP_FW, OP_FWSTART = 0x50, 0x51, 0x52
RSP_ACK, RSP_NACK, RSP_INFO = 0x80, 0x81, 0x82


def crc8(data: bytes) -> int:
    """CRC-8/SMBUS (poly 0x07, init 0x00)."""
    c = 0
    for byte in data:
        c ^= byte
        for _ in range(8):
            c = ((c << 1) ^ 0x07) & 0xFF if (c & 0x80) else (c << 1) & 0xFF
    return c


def frame(cmd: int, payload: bytes = b"") -> bytes:
    """Build a wire frame for a command (useful for testing without serial)."""
    body = bytes([cmd]) + struct.pack("<H", len(payload)) + payload
    return bytes([SYNC]) + body + bytes([crc8(body)])


class DumbTV:
    def __init__(self, port="/dev/serial0", baud=115200, timeout=1.0):
        if serial is None:
            raise RuntimeError("pyserial not installed (pip install pyserial)")
        self.s = serial.Serial(port, baud, timeout=timeout)

    # ---- framing ----
    def _send(self, cmd, payload=b""):
        self.s.write(frame(cmd, payload))

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
        if rcmd == RSP_NACK:
            raise IOError(f"NACK cmd=0x{rpl[0]:02x} err=0x{rpl[1]:02x}")
        return rcmd, rpl

    # ---- high-level API ----
    def info(self):
        _, p = self._cmd(OP_INFO)
        proto, fwma, fwmi, ow, oh, mw, mh, flags = struct.unpack("<BBBHHHHB", p)
        return dict(proto=proto, fw=(fwma, fwmi), osd_w=ow, osd_h=oh,
                    max_w=mw, max_h=mh, flags=flags)

    def enable(self, on):    self._cmd(OP_EN, bytes([1 if on else 0]))
    def alpha(self, a):      self._cmd(OP_ALPHA, bytes([a]))
    def palette(self, i, a, r, g, b):
        self._cmd(OP_PAL, bytes([i, a, r, g, b]))
    def fill(self, addr, count, index):
        self._cmd(OP_FBF, struct.pack("<HH", addr, count) + bytes([index]))
    def write_indices(self, indices, addr=0, chunk=512):
        for i in range(0, len(indices), chunk):
            self._cmd(OP_FBW, struct.pack("<H", addr + i) + bytes(indices[i:i + chunk]))
    def glyph_upload(self, slot, pixels):
        self._cmd(OP_GUP, bytes([slot]) + bytes(pixels))
    def glyph_blit(self, slot, x, y):
        self._cmd(OP_GBLIT, bytes([slot]) + struct.pack("<HH", x, y))
    def draw_text(self, x, y, s):
        b = s.encode("latin-1") if isinstance(s, str) else bytes(s)
        self._cmd(OP_TEXT, struct.pack("<HH", x, y) + b)
    def fill_rect(self, x, y, w, h, index):
        self._cmd(OP_FRECT, struct.pack("<HHHH", x, y, w, h) + bytes([index]))
    def clear(self, index=0):  self._cmd(OP_CLEAR, bytes([index]))
    def flip(self):            self._cmd(OP_FLIP)
    def input_select(self, sel):
        self._cmd(OP_MUXSEL, bytes([sel]))
    def brightness(self, level):  self._cmd(OP_BRIGHT, bytes([level]))  # 128 = neutral
    def contrast(self, level):    self._cmd(OP_CONTR, bytes([level]))   # 128 = unity
    def backlight(self, duty):    self._cmd(OP_BL, bytes([duty]))       # 0..255 PWM
    # on-board RISC-V core firmware
    def fw_halt(self):            self._cmd(OP_FWHALT)
    def fw_start(self):           self._cmd(OP_FWSTART)
    def fw_write(self, addr, data, chunk=512):
        for i in range(0, len(data), chunk):
            self._cmd(OP_FW, struct.pack("<H", addr + i) + bytes(data[i:i + chunk]))
    def load_firmware(self, blob):    # halt -> upload -> run
        self.fw_halt(); self.fw_write(0, blob); self.fw_start()
