"""dumbtv_sim.protocol -- the Dumb-TV framed command protocol.

A software mirror of rtl/cmd_parser.v's framing so the dev-kit sim speaks the
exact same wire protocol as the FPGA:

    A5 | CMD | LEN(16 LE) | PAYLOAD | CRC8      (CRC-8/SMBUS, poly 0x07)

Both paths feed frames through this: the host serial link (host/dumbtv.py) and
the on-board core (its bit-banged UART, decoded by the RISC-V emulator).
"""

import struct

SYNC = 0xA5

# opcodes (match rtl/cmd_parser.v and host/dumbtv.py)
OP_PING, OP_INFO = 0x01, 0x02
OP_EN, OP_ALPHA = 0x10, 0x12
OP_FBW, OP_FBF = 0x20, 0x21
OP_GUP, OP_GBLIT, OP_TEXT, OP_FRECT, OP_PAL = 0x22, 0x23, 0x24, 0x25, 0x26
OP_CLEAR, OP_FLIP, OP_MUXSEL = 0x27, 0x28, 0x40
OP_BRIGHT, OP_CONTR, OP_BL = 0x30, 0x31, 0x32
OP_FWHALT, OP_FW, OP_FWSTART = 0x50, 0x51, 0x52
OP_LVDS = 0x60
RSP_ACK, RSP_NACK, RSP_INFO = 0x80, 0x81, 0x82
ERR_CRC, ERR_LEN, ERR_UNK, ERR_RANGE = 0x01, 0x02, 0x03, 0x04

OPCODE_NAME = {
    v: k for k, v in globals().items() if k.startswith("OP_")
}


def crc8(data: bytes) -> int:
    """CRC-8/SMBUS (poly 0x07, init 0x00)."""
    c = 0
    for byte in data:
        c ^= byte
        for _ in range(8):
            c = ((c << 1) ^ 0x07) & 0xFF if (c & 0x80) else (c << 1) & 0xFF
    return c


def build_frame(cmd: int, payload: bytes = b"") -> bytes:
    body = bytes([cmd]) + struct.pack("<H", len(payload)) + payload
    return bytes([SYNC]) + body + bytes([crc8(body)])


class FrameParser:
    """Incremental byte-stream -> frames. Feed bytes as they arrive (from a
    serial socket or the emulator's bit-banged UART); yields (cmd, payload) for
    each good frame. Bad-CRC / bad-length frames are surfaced with ok=False so
    the caller can mirror the FPGA's NACK behaviour if it wants."""

    def __init__(self):
        self._buf = bytearray()

    def feed(self, data: bytes):
        self._buf.extend(data)
        out = []
        while True:
            frame = self._try_one()
            if frame is None:
                break
            out.append(frame)
        return out

    def _try_one(self):
        b = self._buf
        # resync to SYNC
        while b and b[0] != SYNC:
            del b[0]
        if len(b) < 4:               # SYNC + cmd + len16
            return None
        cmd = b[1]
        length = b[2] | (b[3] << 8)
        total = 4 + length + 1       # + payload + crc
        if len(b) < total:
            return None
        payload = bytes(b[4:4 + length])
        crc = b[4 + length]
        ok = crc == crc8(bytes(b[1:4]) + payload)
        del b[:total]
        return (cmd, payload, ok)
