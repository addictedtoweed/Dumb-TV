"""Headless self-test for the dev-kit core: drive the OSD over the wire protocol,
composite it over a synthetic video frame, and write out.png. No GUI needed --
verifies protocol -> OSD model -> compositor + video end to end.

    python devkit/selftest.py            # writes devkit/out.png
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from dumbtv_sim import OsdModel, Device, VideoBank, compositor          # noqa: E402
from dumbtv_sim.protocol import (build_frame, OP_PAL, OP_EN, OP_ALPHA,   # noqa: E402
                                 OP_CLEAR, OP_FRECT, OP_MUXSEL, OP_BRIGHT,
                                 OP_CONTR, OP_FBW, OP_FLIP, RSP_ACK)
import struct                                                            # noqa: E402


def main():
    osd = OsdModel(osd_w=160, osd_h=90)
    dev = Device(osd)

    def send(cmd, payload=b""):
        rsp = dev.feed(build_frame(cmd, payload))
        assert rsp and rsp[1] == RSP_ACK, f"cmd {cmd:#x} not ACKed: {rsp!r}"

    # palette: 1=opaque white, 2=semi-transparent red, 3=opaque cyan, 4=amber
    send(OP_PAL, bytes([1, 255, 255, 255, 255]))
    send(OP_PAL, bytes([2, 140, 220, 40, 40]))
    send(OP_PAL, bytes([3, 255, 40, 220, 220]))
    send(OP_PAL, bytes([4, 255, 250, 190, 40]))

    send(OP_EN, bytes([1]))
    send(OP_ALPHA, bytes([255]))
    send(OP_CLEAR, bytes([0]))

    # a translucent red panel with a white border and an amber title bar
    send(OP_FRECT, struct.pack("<HHHH", 10, 12, 140, 66) + bytes([2]))
    send(OP_FRECT, struct.pack("<HHHH", 10, 12, 140, 10) + bytes([4]))
    send(OP_FRECT, struct.pack("<HHHH", 10, 12, 140, 1) + bytes([1]))
    send(OP_FRECT, struct.pack("<HHHH", 10, 77, 140, 1) + bytes([1]))
    # a little cyan progress bar via FB_WRITE (one index per byte)
    row = 60
    send(OP_FBW, struct.pack("<H", row * 160 + 20) + bytes([3] * 90))

    send(OP_FLIP)                           # present the back buffer

    send(OP_BRIGHT, bytes([128]))
    send(OP_CONTR, bytes([150]))            # a touch more contrast
    send(OP_MUXSEL, bytes([5]))

    bank = VideoBank(directory=os.path.dirname(__file__), size=(640, 360))
    video = bank.frame(osd.mux_sel, tick=30)
    out = compositor.compose(video, osd)

    print(f"cv2 video decoding: {'yes' if bank.have_cv2 else 'no (synthetic)'}")
    print(f"mux_sel={osd.mux_sel} source={bank.sources[osd.mux_sel]}")
    print(f"composited frame {out.shape} dtype={out.dtype} "
          f"range={out.min()}..{out.max()}")

    outpath = os.path.join(os.path.dirname(__file__), "out.png")
    try:
        from PIL import Image
        Image.fromarray(out).save(outpath)
        print(f"wrote {outpath}")
    except ImportError:
        np.save(outpath.replace(".png", ".npy"), out)
        print("Pillow not installed; wrote .npy instead")


if __name__ == "__main__":
    main()
