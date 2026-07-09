"""dumbtv_sim.compositor -- composite the OSD over a video frame.

A vectorised (numpy) software mirror of rtl/osd_compositor.v: picture controls
on the video, nearest-neighbour upscale of the indexed canvas, palette lookup,
alpha blend, then backlight. Matches the RTL's integer math:

    video':  clamp((v-128)*contrast >> 7 + brightness)
    weight:  show ? ((pa+(pa>>7)) * (alpha+(alpha>>7)) >> 8) : 0      (0..256)
    out:     (video'*(256-w) + overlay*w) >> 8
    panel:   out * backlight / 255
"""

import numpy as np


def compose(video_rgb, osd):
    """video_rgb: HxWx3 uint8 -> composited HxWx3 uint8."""
    H, W = video_rgb.shape[:2]

    # picture controls on the video (arithmetic >>7 floors like Verilog >>>)
    v = video_rgb.astype(np.int32)
    vv = ((v - 128) * int(osd.contrast) >> 7) + int(osd.brightness)
    np.clip(vv, 0, 255, out=vv)

    # nearest-neighbour upscale of the shown canvas to the video resolution
    ys = (np.arange(H) * osd.OSD_H) // H
    xs = (np.arange(W) * osd.OSD_W) // W
    idx = osd.shown[np.ix_(ys, xs)]                      # HxW indices

    pal = osd.palette.astype(np.int32)                  # 16x4 ARGB
    argb = pal[idx]                                     # HxWx4
    pa = argb[..., 0]
    overlay = argb[..., 1:4]                            # R,G,B

    pa_w = pa + (pa >> 7)
    master = int(osd.osd_alpha) + (int(osd.osd_alpha) >> 7)
    eff = (pa_w * master) >> 8                          # 0..256
    show = (osd.osd_enable != 0) & (idx != 0)
    w = np.where(show, eff, 0)[..., None]               # HxWx1

    out = (vv * (256 - w) + overlay * w) >> 8
    if osd.backlight != 255:
        out = out * int(osd.backlight) // 255
    return out.astype(np.uint8)
