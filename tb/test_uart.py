"""cocotb testbench for the UART control plane (top_uart), indexed OSD.

Bit-bangs framed protocol bytes into RX, decodes the device's TX responses, and
verifies the full chain: PING/ACK, GET_INFO, bad-CRC NACK, out-of-range NACK,
and a complete overlay upload (PALETTE_SET + FB_WRITE indices + ENABLE) that
must then appear, upscaled and palette-mapped, in the video output.

Run with:  make TOPLEVEL=top_uart MODULE=test_uart
"""

import struct
from collections import deque
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

CLKS_PER_BIT = 8
SYNC = 0xA5

# geometry (match top_uart + video_timing defaults)
H_TOTAL, V_TOTAL = 22, 11
FRAME_CYCLES = H_TOTAL * V_TOTAL
ACTIVE_W, ACTIVE_H = 16, 8
OSD_W, OSD_H = 8, 4
X_STEP = (OSD_W << 16) // ACTIVE_W
Y_STEP = (OSD_H << 16) // ACTIVE_H

# opcodes
OP_PING, OP_INFO = 0x01, 0x02
OP_EN, OP_ALPHA = 0x10, 0x12
OP_FBW, OP_FBF, OP_PAL = 0x20, 0x21, 0x26
RSP_ACK, RSP_NACK, RSP_INFO = 0x80, 0x81, 0x82


def crc8(data: bytes) -> int:
    c = 0
    for byte in data:
        c ^= byte
        for _ in range(8):
            c = ((c << 1) ^ 0x07) & 0xFF if (c & 0x80) else (c << 1) & 0xFF
    return c


# ---- models mirroring the RTL ----
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
    return (cx + 2 * cy) & 3          # indices 0..3 (0 = transparent)

PAL = {0: (0, 0, 0, 0),
       1: (255, 200, 50, 10),
       2: (200, 20, 200, 100),
       3: (128, 80, 10, 240)}        # index -> (A, R, G, B)


# ---- UART line driving / sampling ----
async def clks(dut, n):
    for _ in range(n):
        await RisingEdge(dut.clk)


async def send_byte(dut, val):
    dut.rx.value = 0
    await clks(dut, CLKS_PER_BIT)
    for i in range(8):
        dut.rx.value = (val >> i) & 1
        await clks(dut, CLKS_PER_BIT)
    dut.rx.value = 1
    await clks(dut, CLKS_PER_BIT)
    await clks(dut, CLKS_PER_BIT)


async def send_frame(dut, cmd, payload=b""):
    body = bytes([cmd]) + struct.pack("<H", len(payload)) + payload
    for b in bytes([SYNC]) + body + bytes([crc8(body)]):
        await send_byte(dut, b)


async def recv_byte(dut):
    while int(dut.tx.value) == 1:
        await RisingEdge(dut.clk)
    await clks(dut, CLKS_PER_BIT + CLKS_PER_BIT // 2)
    val = 0
    for i in range(8):
        val |= (int(dut.tx.value) & 1) << i
        await clks(dut, CLKS_PER_BIT)
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
        await RisingEdge(dut.clk)
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


async def reset(dut):
    dut.rx.value = 1
    dut.rst.value = 1
    await clks(dut, 20)
    dut.rst.value = 0
    await clks(dut, 5)


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
async def test_ping(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset(dut)
    q = start_monitor(dut)
    await send_frame(dut, OP_PING)
    cmd, pl = await recv_frame(dut, q)
    assert cmd == RSP_ACK and pl == bytes([OP_PING]), (hex(cmd), pl)


@cocotb.test()
async def test_get_info(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset(dut)
    q = start_monitor(dut)
    await send_frame(dut, OP_INFO)
    cmd, pl = await recv_frame(dut, q)
    assert cmd == RSP_INFO, hex(cmd)
    _, _, _, ow, oh, _, _, flags = struct.unpack("<BBBHHHHB", pl)
    assert (ow, oh) == (OSD_W, OSD_H), (ow, oh)


@cocotb.test()
async def test_bad_crc(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset(dut)
    q = start_monitor(dut)
    for b in [SYNC, OP_PING, 0x00, 0x00, 0xEE]:
        await send_byte(dut, b)
    cmd, pl = await recv_frame(dut, q)
    assert cmd == RSP_NACK and pl[0] == OP_PING and pl[1] == 0x01, (hex(cmd), pl)


@cocotb.test()
async def test_fb_range(dut):
    """FB_WRITE that runs past the canvas end returns NACK(range=0x04)."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset(dut)
    q = start_monitor(dut)
    # depth = OSD_W*OSD_H = 32; start at 30 with 4 indices -> 32,33 out of range
    payload = struct.pack("<H", 30) + bytes([0, 0, 0, 0])
    await send_frame(dut, OP_FBW, payload)
    cmd, pl = await recv_frame(dut, q)
    assert cmd == RSP_NACK and pl[0] == OP_FBW and pl[1] == 0x04, (hex(cmd), pl)


@cocotb.test()
async def test_overlay_upload(dut):
    """Upload a palette + indexed canvas over UART; verify it appears upscaled
    and palette-mapped in the video output."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset(dut)
    q = start_monitor(dut)

    # palette
    for i, (a, r, g, b) in PAL.items():
        await send_frame(dut, OP_PAL, bytes([i, a, r, g, b]))
        cmd, _ = await recv_frame(dut, q); assert cmd == RSP_ACK

    # canvas indices, linear addr = cy*OSD_W + cx
    indices = bytes([canvas_idx(a % OSD_W, a // OSD_W) for a in range(OSD_W * OSD_H)])
    await send_frame(dut, OP_FBW, struct.pack("<H", 0) + indices)
    cmd, _ = await recv_frame(dut, q); assert cmd == RSP_ACK

    master = 200
    await send_frame(dut, OP_ALPHA, bytes([master]))
    cmd, _ = await recv_frame(dut, q); assert cmd == RSP_ACK
    await send_frame(dut, OP_EN, bytes([1]))
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
