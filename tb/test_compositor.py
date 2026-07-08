"""cocotb testbench for the full-screen indexed OSD compositor (top).

Loads a palette and a canvas of 4-bit indices via the direct write ports, then
checks the output pixel-for-pixel: each active screen pixel maps (via the
nearest-neighbour upscaler) to a canvas texel, whose palette color is blended
over the video. Index 0 is transparent.

Run with:  make    (TOPLEVEL=top MODULE=test_compositor)
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

# geometry (match top / video_timing defaults)
H_TOTAL, V_TOTAL = 22, 11
FRAME_CYCLES = H_TOTAL * V_TOTAL
ACTIVE_W, ACTIVE_H = 16, 8
OSD_W, OSD_H = 8, 4
X_STEP = (OSD_W << 16) // ACTIVE_W
Y_STEP = (OSD_H << 16) // ACTIVE_H

# ctrl_regs addresses
A_ENABLE, A_ALPHA = 0, 1


def pattern(x, y):
    return (x & 0xFF, y & 0xFF, 0x40)


def _w(a):
    return a + (a >> 7)          # 0..255 alpha -> 0..256 weight


def blend(vid, ov, w):
    return (vid * (256 - w) + ov * w) >> 8


def eff_alpha(pa, master):
    return (_w(pa) * _w(master)) >> 8


def canvas_addr(cx, cy):
    return cy * OSD_W + cx


def scale(x, y):
    return ((x * X_STEP) >> 16, (y * Y_STEP) >> 16)


# the OSD content the test loads
def canvas_idx(cx, cy):
    return (cx + 2 * cy) & 3     # indices 0..3 (0 = transparent)

PAL = {0: (0, 0, 0, 0),
       1: (255, 200, 50, 10),
       2: (200, 20, 200, 100),
       3: (128, 80, 10, 240)}    # index -> (A, R, G, B)


async def reset(dut):
    dut.rst.value = 1
    dut.ctrl_we.value = 0
    dut.ctrl_addr.value = 0
    dut.ctrl_wdata.value = 0
    dut.fb_we.value = 0
    dut.fb_waddr.value = 0
    dut.fb_wdata.value = 0
    dut.pal_we.value = 0
    dut.pal_waddr.value = 0
    dut.pal_wdata.value = 0
    dut.flip_req.value = 0
    for _ in range(5):
        await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)


async def flip(dut):
    """Request a buffer swap and wait for it to be applied (at VSync)."""
    prev = int(dut.flip_done.value)
    dut.flip_req.value = 1 - int(dut.flip_req.value)
    for _ in range(3 * FRAME_CYCLES):
        await RisingEdge(dut.clk)
        if int(dut.flip_done.value) != prev:
            return
    raise TimeoutError("flip not acknowledged")


async def wr_ctrl(dut, addr, data):
    await RisingEdge(dut.clk)
    dut.ctrl_addr.value = addr
    dut.ctrl_wdata.value = data
    dut.ctrl_we.value = 1
    await RisingEdge(dut.clk)
    dut.ctrl_we.value = 0


async def wr_fb(dut, addr, idx):
    await RisingEdge(dut.clk)
    dut.fb_waddr.value = addr
    dut.fb_wdata.value = idx
    dut.fb_we.value = 1
    await RisingEdge(dut.clk)
    dut.fb_we.value = 0


async def wr_pal(dut, idx, a, r, g, b):
    await RisingEdge(dut.clk)
    dut.pal_waddr.value = idx
    dut.pal_wdata.value = (a << 24) | (r << 16) | (g << 8) | b
    dut.pal_we.value = 1
    await RisingEdge(dut.clk)
    dut.pal_we.value = 0


async def load_osd(dut):
    for i, (a, r, g, b) in PAL.items():
        await wr_pal(dut, i, a, r, g, b)
    for cy in range(OSD_H):
        for cx in range(OSD_W):
            await wr_fb(dut, canvas_addr(cx, cy), canvas_idx(cx, cy))


async def capture_frame(dut, n_frames=6):
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
    """OSD disabled -> output equals the input gradient exactly."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset(dut)
    await load_osd(dut)
    await wr_ctrl(dut, A_ENABLE, 0)
    frame = await capture_frame(dut)
    assert frame
    for (x, y), got in frame.items():
        assert got == pattern(x, y), f"passthrough ({x},{y}): {got} != {pattern(x, y)}"


@cocotb.test()
async def test_indexed_overlay(dut):
    """OSD enabled -> upscaled canvas index -> palette color blended over video,
    index 0 transparent."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset(dut)
    await load_osd(dut)          # palette + canvas written to the BACK buffer
    master = 200
    await wr_ctrl(dut, A_ALPHA, master)
    await wr_ctrl(dut, A_ENABLE, 1)

    # double-buffer: nothing drawn is visible until FLIP -> still passthrough
    pre = await capture_frame(dut)
    for (x, y), got in pre.items():
        assert got == pattern(x, y), f"pre-flip not passthrough at ({x},{y}): {got}"

    await flip(dut)
    frame = await capture_frame(dut)
    assert frame
    seen_color = seen_transparent = False
    for (x, y), got in frame.items():
        vr, vg, vb = pattern(x, y)
        cx, cy = scale(x, y)
        idx = canvas_idx(cx, cy)
        if idx != 0:
            seen_color = True
            a, r, g, b = PAL[idx]
            w = eff_alpha(a, master)
            exp = (blend(vr, r, w), blend(vg, g, w), blend(vb, b, w))
        else:
            seen_transparent = True
            exp = (vr, vg, vb)
        assert got == exp, f"({x},{y}) idx={idx}: {got} != {exp}"
    assert seen_color and seen_transparent
