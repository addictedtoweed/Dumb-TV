"""cocotb testbench for the two-clock parallel-RGB top (top_rgb).

The control plane (UART) runs on sclk; the video pipeline runs on an
independent pclk. The clocks are deliberately asynchronous so the two clock
crossings -- the dual-clock OSD framebuffer and the sync2 config bus -- are
actually exercised. The overlay-upload test proves a serial upload on sclk lands
correctly in the pixel-domain video output.

Run with:  make TOPLEVEL=top_rgb MODULE=test_rgb
"""

import struct
from collections import deque
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

CLKS_PER_BIT = 8          # in sclk cycles (must match top_rgb default)
SCLK_NS = 10
PCLK_NS = 14              # intentionally async to sclk
SYNC = 0xA5

H_TOTAL, V_TOTAL = 22, 11
FRAME_CYCLES = H_TOTAL * V_TOTAL
OSD_W, OSD_H = 8, 4

OP_PING, OP_INFO = 0x01, 0x02
OP_EN, OP_WIN, OP_ALPHA = 0x10, 0x11, 0x12
OP_FBW, OP_FBF = 0x20, 0x21
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
    return a + (a >> 7)          # 0..255 alpha -> 0..256 weight


def blend(vid, ov, w):
    return (vid * (256 - w) + ov * w) >> 8


def eff_alpha(fb_a, master):
    return (_w(fb_a) * _w(master)) >> 8


def osd_image(cx, cy):
    a = 255 if ((cx + cy) & 1) == 0 else 128
    return (a, (cx * 16) & 0xFF, (cy * 32) & 0xFF, 0xAA)


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
    """Serial upload on sclk must appear blended in the pclk video output,
    crossing both the dual-clock framebuffer and the sync2 config bus."""
    start_clocks(dut)
    await reset(dut)
    q = start_monitor(dut)

    await send_frame(dut, OP_FBF, struct.pack("<HH", 0, OSD_W * OSD_H) + bytes([0, 0, 0, 0]))
    cmd, _ = await recv_frame(dut, q); assert cmd == RSP_ACK

    texels = bytearray()
    for cy in range(OSD_H):
        for cx in range(OSD_W):
            a, r, g, b = osd_image(cx, cy)
            texels += bytes([a, r, g, b])
    await send_frame(dut, OP_FBW, struct.pack("<H", 0) + bytes(texels))
    cmd, _ = await recv_frame(dut, q); assert cmd == RSP_ACK

    x0, y0, w, h, master = 4, 2, OSD_W, OSD_H, 200
    await send_frame(dut, OP_WIN, struct.pack("<HHHH", x0, y0, w, h))
    cmd, _ = await recv_frame(dut, q); assert cmd == RSP_ACK
    await send_frame(dut, OP_ALPHA, bytes([master]))
    cmd, _ = await recv_frame(dut, q); assert cmd == RSP_ACK
    await send_frame(dut, OP_EN, bytes([1]))
    cmd, _ = await recv_frame(dut, q); assert cmd == RSP_ACK

    # let the config CDC + framebuffer settle into the pixel domain
    await sclks(dut, 50)

    frame = await capture_frame(dut)
    assert frame, "no video captured"
    inside_seen = False
    for (x, y), got in frame.items():
        vr, vg, vb = pattern(x, y)
        if x0 <= x < x0 + w and y0 <= y < y0 + h:
            inside_seen = True
            a, fr, fg, fb_ = osd_image(x - x0, y - y0)
            ea = eff_alpha(a, master)
            exp = (blend(vr, fr, ea), blend(vg, fg, ea), blend(vb, fb_, ea))
        else:
            exp = (vr, vg, vb)
        assert got == exp, f"pixel ({x},{y}): {got} != {exp}"
    assert inside_seen, "overlay window never appeared"
