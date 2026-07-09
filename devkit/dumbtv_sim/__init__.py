"""dumbtv_sim -- a pure-Python functional twin of the Dumb-TV FPGA.

Speaks the exact framed command protocol (protocol.py), applies it to a software
OSD (osd.py), composites over 16 looped video streams (video.py + compositor.py),
and -- with the RISC-V emulator (riscv.py) -- runs the same on-board firmware the
FPGA would. For fast, interactive OSD + firmware + IR-learning development; the
RTL stays the hardware source of truth.
"""

from .osd import OsdModel
from .device import Device
from .video import VideoBank
from . import compositor, protocol

__all__ = ["OsdModel", "Device", "VideoBank", "compositor", "protocol"]
