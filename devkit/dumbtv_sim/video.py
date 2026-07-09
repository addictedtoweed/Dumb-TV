"""dumbtv_sim.video -- 16 looped RGB video streams for the input mux.

Looks for vid_0 .. vid_15 (any common extension) in a directory and decodes them
with OpenCV (so you don't re-encode -- it reads mp4/mkv/mov/... via ffmpeg),
looping each. Any missing stream falls back to a distinct animated synthetic
pattern, so the sim runs with zero video files and every input still looks
different (useful for testing the 16-way mux).
"""

import glob
import os

import numpy as np

try:
    import cv2                       # optional; enables real video decoding
except ImportError:
    cv2 = None

EXTS = ("mp4", "mkv", "mov", "avi", "webm", "m4v", "y4m")


def _synth(i, W, H, tick):
    """A distinct animated test pattern for stream i (no file needed)."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    hue = (i / 16.0 + 0.03 * np.sin(tick * 0.05)) % 1.0
    # simple hue -> rgb
    base = np.array([0.5 + 0.5 * np.cos(2 * np.pi * (hue + p)) for p in (0, 1 / 3, 2 / 3)])
    frame = np.zeros((H, W, 3), np.float32)
    # moving diagonal band + soft vignette so motion is visible
    band = 0.5 + 0.5 * np.sin((xx + yy) * 0.03 - tick * 0.12)
    for c in range(3):
        frame[..., c] = base[c] * (0.35 + 0.65 * band)
    # count-of-i marker: (i+1) bright blocks across the top so the stream is IDable
    bw = max(4, W // 20)
    for k in range(i + 1):
        x0 = 8 + k * (bw + 4)
        if x0 + bw < W:
            frame[8:8 + bw, x0:x0 + bw] = 1.0
    return (np.clip(frame, 0, 1) * 255).astype(np.uint8)


class _Stream:
    def __init__(self, path, W, H):
        self.W, self.H = W, H
        self.cap = cv2.VideoCapture(path) if (cv2 and path) else None
        if self.cap is not None and not self.cap.isOpened():
            self.cap = None
        self.path = path

    def frame(self, i, tick):
        if self.cap is None:
            return _synth(i, self.W, self.H, tick)
        ok, bgr = self.cap.read()
        if not ok:                                   # loop
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, bgr = self.cap.read()
            if not ok:
                return _synth(i, self.W, self.H, tick)
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        if rgb.shape[1] != self.W or rgb.shape[0] != self.H:
            rgb = cv2.resize(rgb, (self.W, self.H), interpolation=cv2.INTER_AREA)
        return rgb


class VideoBank:
    def __init__(self, directory=".", size=(640, 360), n=16):
        self.W, self.H = size
        self.n = n
        self.streams = []
        for i in range(n):
            path = None
            for ext in EXTS:
                hits = glob.glob(os.path.join(directory, "vid_%d.%s" % (i, ext)))
                if hits:
                    path = hits[0]
                    break
            self.streams.append(_Stream(path, self.W, self.H))
        self.have_cv2 = cv2 is not None
        self.sources = [s.path or "(synthetic)" for s in self.streams]

    def frame(self, i, tick):
        i = max(0, min(self.n - 1, int(i)))
        return self.streams[i].frame(i, tick)
