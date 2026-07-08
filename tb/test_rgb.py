"""cocotb testbench for the two-clock parallel-RGB top (top_rgb), indexed OSD.

Control plane (UART) runs on sclk; video runs on an asynchronous pclk. The
overlay-upload test proves a serial upload on sclk (palette + indexed canvas)
lands correctly in the pixel-domain video output, crossing the dual-clock canvas
and palette RAMs and the sync2 config bus.

Run with:  make TOPLEVEL=top_rgb MODULE=test_rgb
"""

import struct
from collections import deque
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

CLKS_PER_BIT = 8
SCLK_NS = 10
PCLK_NS = 14              # intentionally async to sclk
SYNC = 0xA5

H_TOTAL, V_TOTAL = 22, 11
FRAME_CYCLES = H_TOTAL * V_TOTAL
ACTIVE_W, ACTIVE_H = 16, 8
OSD_W, OSD_H = 8, 4
X_STEP = (OSD_W << 16) // ACTIVE_W
Y_STEP = (OSD_H << 16) // ACTIVE_H

OP_PING, OP_INFO = 0x01, 0x02
OP_EN, OP_ALPHA = 0x10, 0x12
OP_FBW, OP_FBF, OP_PAL = 0x20, 0x21, 0x26
OP_CLEAR, OP_FLIP = 0x27, 0x28
RSP_ACK, RSP_NACK, RSP_INFO = 0x80, 0x81, 0x82


def crc8(data: bytes) -> int:
    c = 0
    for byte in data:
        c ^= byte
        for _ in range(8):
            c = ((c << 1) ^ 0x07) & 0xFF if (c & 0x80) else (c << 1) & 0xFF
    return c


def pattern(x, y):
    return (x & 0xFF, y & 0xFF, 0x40)


def _w(a):
    return a + (a >> 7)


def blend(vid, ov, w):
    return (vid * (256 - w) + ov * w) >> 8


def eff_alpha(pa, master):
    return (_w(pa) * _w(master)) >> 8


def scale(x, y):
    return ((x * X_STEP) >> 16, (y * Y_STEP) >> 16)


def canvas_idx(cx, cy):
    return (cx + 2 * cy) & 3

PAL = {0: (0, 0, 0, 0),
       1: (255, 200, 50, 10),
       2: (200, 20, 200, 100),
       3: (128, 80, 10, 240)}


# ---- sclk-domain (UART) helpers ----
async def sclks(dut, n):
    for _ in range(n):
        await RisingEdge(dut.sclk)


async def send_byte(dut, val):
    dut.rx.value = 0
    await sclks(dut, CLKS_PER_BIT)
    for i in range(8):
        dut.rx.value = (val >> i) & 1
        await sclks(dut, CLKS_PER_BIT)
    dut.rx.value = 1
    await sclks(dut, CLKS_PER_BIT)
    await sclks(dut, CLKS_PER_BIT)


async def send_frame(dut, cmd, payload=b""):
    body = bytes([cmd]) + struct.pack("<H", len(payload)) + payload
    for b in bytes([SYNC]) + body + bytes([crc8(body)]):
        await send_byte(dut, b)


async def recv_byte(dut):
    while int(dut.tx.value) == 1:
        await RisingEdge(dut.sclk)
    await sclks(dut, CLKS_PER_BIT + CLKS_PER_BIT // 2)
    val = 0
    for i in range(8):
        val |= (int(dut.tx.value) & 1) << i
        await sclks(dut, CLKS_PER_BIT)
    return val


async def uart_tx_monitor(dut, q):
    while True:
        q.append(await recv_byte(dut))


def start_monitor(dut):
    q = deque()
    cocotb.start_soon(uart_tx_monitor(dut, q))
    return q


async def get_byte(dut, q):
    while not q:
        await RisingEdge(dut.sclk)
    return q.popleft()


async def recv_frame(dut, q):
    sync = await get_byte(dut, q)
    assert sync == SYNC, f"bad sync 0x{sync:02x}"
    cmd = await get_byte(dut, q)
    lo = await get_byte(dut, q)
    hi = await get_byte(dut, q)
    length = lo | (hi << 8)
    payload = bytes([await get_byte(dut, q) for _ in range(length)])
    crc = await get_byte(dut, q)
    assert crc == crc8(bytes([cmd, lo, hi]) + payload), "bad response CRC"
    return cmd, payload


# ---- pclk-domain (video) capture ----
async def capture_frame(dut, n_frames=6):
    frame = {}
    ox = oy = prev_de = 0
    for _ in range(n_frames * FRAME_CYCLES):
        await RisingEdge(dut.pclk)
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


async def reset(dut):
    dut.rx.value = 1
    dut.rst.value = 1
    await sclks(dut, 20)
    dut.rst.value = 0
    await sclks(dut, 5)


def start_clocks(dut):
    cocotb.start_soon(Clock(dut.sclk, SCLK_NS, units="ns").start())
    cocotb.start_soon(Clock(dut.pclk, PCLK_NS, units="ns").start())


@cocotb.test()
async def test_ping(dut):
    start_clocks(dut)
    await reset(dut)
    q = start_monitor(dut)
    await send_frame(dut, OP_PING)
    cmd, pl = await recv_frame(dut, q)
    assert cmd == RSP_ACK and pl == bytes([OP_PING]), (hex(cmd), pl)


@cocotb.test()
async def test_get_info(dut):
    start_clocks(dut)
    await reset(dut)
    q = start_monitor(dut)
    await send_frame(dut, OP_INFO)
    cmd, pl = await recv_frame(dut, q)
    assert cmd == RSP_INFO, hex(cmd)
    _, _, _, ow, oh, _, _, _ = struct.unpack("<BBBHHHHB", pl)
    assert (ow, oh) == (OSD_W, OSD_H), (ow, oh)


@cocotb.test()
async def test_overlay_upload(dut):
    """Serial upload on sclk (palette + indexed canvas) must appear upscaled and
    palette-mapped in the pclk video output, crossing both dual-clock RAMs and
    the sync2 config bus."""
    start_clocks(dut)
    await reset(dut)
    q = start_monitor(dut)

    for i, (a, r, g, b) in PAL.items():
        await send_frame(dut, OP_PAL, bytes([i, a, r, g, b]))
        cmd, _ = await recv_frame(dut, q); assert cmd == RSP_ACK

    indices = bytes([canvas_idx(a % OSD_W, a // OSD_W) for a in range(OSD_W * OSD_H)])
    await send_frame(dut, OP_FBW, struct.pack("<H", 0) + indices)
    cmd, _ = await recv_frame(dut, q); assert cmd == RSP_ACK

    master = 200
    await send_frame(dut, OP_ALPHA, bytes([master]))
    cmd, _ = await recv_frame(dut, q); assert cmd == RSP_ACK
    await send_frame(dut, OP_EN, bytes([1]))
    cmd, _ = await recv_frame(dut, q); assert cmd == RSP_ACK

    await sclks(dut, 50)   # let the enable/alpha config CDC settle into pixel domain

    # double-buffer: upload landed in the back buffer -> not visible yet
    pre = await capture_frame(dut)
    for (x, y), got in pre.items():
        assert got == pattern(x, y), f"pre-flip not passthrough at ({x},{y}): {got}"

    # FLIP crosses sclk->pclk, swaps at VSync, and only ACKs after the swap
    await send_frame(dut, OP_FLIP)
    cmd, _ = await recv_frame(dut, q); assert cmd == RSP_ACK

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
