"""cocotb testbench for the OSD compositor pipeline (framebuffer OSD).

Runs the whole top-level (timing + pattern + ctrl + framebuffer + compositor)
in Verilator, loads an OSD image into the framebuffer, reconstructs each output
frame from out_de/out_vsync, and checks every pixel against a Python model of
the exact gradient + per-pixel-alpha blend math.

Run with:  make           (see ../Makefile)
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

# Control register map (must match rtl/ctrl_regs.v)
A_ENABLE, A_X0, A_Y0, A_W, A_H, A_ALPHA = range(6)

# Tiny default timing baked into video_timing.v
H_ACTIVE, H_TOTAL = 16, 22   # 16 + 2 + 2 + 2
V_ACTIVE, V_TOTAL = 8, 11    # 8 + 1 + 1 + 1
FRAME_CYCLES = H_TOTAL * V_TOTAL

# OSD framebuffer size (must match top.v defaults: OSD_W, OSD_H)
OSD_W, OSD_H = 8, 4
LX = OSD_W.bit_length() - 1   # log2, OSD_W is a power of two


def pattern(x, y):
    """Mirror of rtl/pattern_gen.v."""
    return (x & 0xFF, y & 0xFF, 0x40)


def blend(vid, ov, a):
    """Mirror of blend8() in rtl/osd_compositor.v."""
    return (vid * (256 - a) + ov * a) >> 8


def eff_alpha(fb_a, master):
    """Mirror of eff_a in rtl/osd_compositor.v."""
    return (fb_a * master) >> 8


def osd_image(cx, cy):
    """The OSD image we load into the framebuffer. Returns (a, r, g, b)."""
    a = 255 if ((cx + cy) & 1) == 0 else 128   # checkerboard transparency
    return (a, (cx * 16) & 0xFF, (cy * 32) & 0xFF, 0xAA)


async def reset(dut):
    dut.rst.value = 1
    dut.ctrl_we.value = 0
    dut.ctrl_addr.value = 0
    dut.ctrl_wdata.value = 0
    dut.fb_we.value = 0
    dut.fb_waddr.value = 0
    dut.fb_wdata.value = 0
    for _ in range(5):
        await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)


async def wr(dut, addr, data):
    """Single-cycle control-register write."""
    await RisingEdge(dut.clk)
    dut.ctrl_addr.value = addr
    dut.ctrl_wdata.value = data
    dut.ctrl_we.value = 1
    await RisingEdge(dut.clk)
    dut.ctrl_we.value = 0


async def fb_write(dut, cx, cy, a, r, g, b):
    """Single-cycle framebuffer write at texel (cx, cy)."""
    addr = (cy << LX) | cx
    word = (a << 24) | (r << 16) | (g << 8) | b
    await RisingEdge(dut.clk)
    dut.fb_waddr.value = addr
    dut.fb_wdata.value = word
    dut.fb_we.value = 1
    await RisingEdge(dut.clk)
    dut.fb_we.value = 0


async def load_osd_image(dut):
    for cy in range(OSD_H):
        for cx in range(OSD_W):
            a, r, g, b = osd_image(cx, cy)
            await fb_write(dut, cx, cy, a, r, g, b)


async def capture_frame(dut, n_frames=5):
    """Run for n_frames and return {(x,y): (r,g,b)} for the output stream."""
    frame = {}
    ox = oy = prev_de = 0
    for _ in range(n_frames * FRAME_CYCLES):
        await RisingEdge(dut.clk)
        de = int(dut.out_de.value)
        vs = int(dut.out_vsync.value)
        if vs:
            oy = 0
        elif prev_de and not de:
            oy += 1
        if de:
            frame[(ox, oy)] = (int(dut.out_r.value),
                               int(dut.out_g.value),
                               int(dut.out_b.value))
            ox += 1
        else:
            ox = 0
        prev_de = de
    return frame


@cocotb.test()
async def test_passthrough(dut):
    """OSD disabled -> output must equal the input gradient exactly."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset(dut)
    await wr(dut, A_ENABLE, 0)

    frame = await capture_frame(dut)
    assert frame, "captured no active pixels"
    for (x, y), got in frame.items():
        assert got == pattern(x, y), \
            f"passthrough mismatch at ({x},{y}): {got} != {pattern(x, y)}"


@cocotb.test()
async def test_framebuffer_overlay(dut):
    """OSD enabled -> per-pixel framebuffer texel blended over video inside the
    window (with master fade), passthrough outside."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset(dut)

    await load_osd_image(dut)

    x0, y0, w, h, master = 4, 2, OSD_W, OSD_H, 200
    await wr(dut, A_X0, x0)
    await wr(dut, A_Y0, y0)
    await wr(dut, A_W, w)
    await wr(dut, A_H, h)
    await wr(dut, A_ALPHA, master)
    await wr(dut, A_ENABLE, 1)

    frame = await capture_frame(dut)
    assert frame, "captured no active pixels"

    inside_seen = False
    for (x, y), got in frame.items():
        vr, vg, vb = pattern(x, y)
        if x0 <= x < x0 + w and y0 <= y < y0 + h:
            inside_seen = True
            cx, cy = x - x0, y - y0
            a, fr, fg, fb_ = osd_image(cx, cy)
            ea = eff_alpha(a, master)
            exp = (blend(vr, fr, ea), blend(vg, fg, ea), blend(vb, fb_, ea))
        else:
            exp = (vr, vg, vb)
        assert got == exp, \
            f"overlay mismatch at ({x},{y}): {got} != {exp}"
    assert inside_seen, "OSD window never appeared in the frame"
