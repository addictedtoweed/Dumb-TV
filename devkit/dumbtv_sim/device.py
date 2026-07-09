"""dumbtv_sim.device -- byte-stream front door to the OSD model.

Wraps an OsdModel with a FrameParser so anything that produces the wire protocol
-- the host serial link, or the on-board core's bit-banged UART (via the RISC-V
emulator) -- can drive it the same way. feed(bytes) applies whole frames and
returns the response bytes (ACK/NACK/INFO), exactly like the FPGA's UART TX.
"""

from . import protocol as P
from .protocol import FrameParser, build_frame


class Device:
    def __init__(self, osd):
        self.osd = osd
        self.parser = FrameParser()

    def feed(self, data: bytes) -> bytes:
        out = bytearray()
        for cmd, payload, ok in self.parser.feed(data):
            if not ok:
                rc, rp = P.RSP_NACK, bytes([cmd, P.ERR_CRC])
            else:
                rc, rp = self.osd.apply(cmd, payload)
            out += build_frame(rc, rp)
        return bytes(out)
