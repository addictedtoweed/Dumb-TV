"""cocotb testbench for the UART control plane (top_uart).

Bit-bangs framed protocol bytes into the RX line, decodes the device's TX
responses, and verifies the full chain: PING/ACK, GET_INFO, bad-CRC NACK, and a
complete overlay upload (FILL clear -> FB_WRITE image -> WINDOW/ALPHA/ENABLE)
that must then appear blended in the video output.

Run with:  make TOPLEVEL=top_uart MODULE=test_uart
"""

import struct
from collections import deque
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

CLKS_PER_BIT = 8        # must match top_uart default
SYNC = 0xA5

# Video / framebuffer geometry (match top_uart + video_timing defaults)
H_TOTAL, V_TOTAL = 22, 11
FRAME_CYCLES = H_TOTAL * V_TOTAL
OSD_W, OSD_H = 8, 4

# Opcodes
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


# ---- models mirroring the RTL ----
def pattern(x, y):
    return (x & 0xFF, y & 0xFF, 0x40)


def _w(a):
    return a + (a >> 7)          # 0..255 alpha -> 0..256 weight


def blend(vid, ov, w):
    return (vid * (256 - w) + ov * w) >> 8


def eff_alpha(fb_a, master):
    return (_w(fb_a) * _w(master)) >> 8


def osd_image(cx, cy):
    """The overlay we upload. Returns (A, R, G, B)."""
    a = 255 if ((cx + cy) & 1) == 0 else 128
    return (a, (cx * 16) & 0xFF, (cy * 32) & 0xFF, 0xAA)


# ---- UART line driving / sampling ----
async def clks(dut, n):
    for _ in range(n):
        await RisingEdge(dut.clk)


async def send_byte(dut, val):
    dut.rx.value = 0                       # start bit
    await clks(dut, CLKS_PER_BIT)
    for i in range(8):                     # data, LSB first
        dut.rx.value = (val >> i) & 1
        await clks(dut, CLKS_PER_BIT)
    dut.rx.value = 1                       # stop bit
    await clks(dut, CLKS_PER_BIT)
    await clks(dut, CLKS_PER_BIT)          # inter-byte idle


async def send_frame(dut, cmd, payload=b""):
    body = bytes([cmd]) + struct.pack("<H", len(payload)) + payload
    for b in bytes([SYNC]) + body + bytes([crc8(body)]):
        await send_byte(dut, b)


async def recv_byte(dut):
    # block until the start bit (TX idles high, falls low to start), then
    # sample each bit at its center. No timeout: this is driven by a always-on
    # monitor, so idle gaps between response frames are normal.
    while int(dut.tx.value) == 1:
        await RisingEdge(dut.clk)
    await clks(dut, CLKS_PER_BIT + CLKS_PER_BIT // 2)   # center of bit 0
    val = 0
    for i in range(8):
        val |= (int(dut.tx.value) & 1) << i
        await clks(dut, CLKS_PER_BIT)
    return val


async def uart_tx_monitor(dut, q):
    """Continuously decode the device TX line into a byte queue."""
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
    await clks(dut, 10)
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
    proto, fwma, fwmi, ow, oh, mw, mh, flags = struct.unpack("<BBBHHHHB", pl)
    assert (ow, oh) == (OSD_W, OSD_H), (ow, oh)


@cocotb.test()
async def test_bad_crc(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset(dut)
    q = start_monitor(dut)
    # PING frame with deliberately wrong CRC
    for b in [SYNC, OP_PING, 0x00, 0x00, 0xEE]:
        await send_byte(dut, b)
    cmd, pl = await recv_frame(dut, q)
    assert cmd == RSP_NACK and pl[0] == OP_PING and pl[1] == 0x01, (hex(cmd), pl)


@cocotb.test()
async def test_fb_range(dut):
    """FB_WRITE that runs past the framebuffer end returns NACK(range=0x04)."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset(dut)
    q = start_monitor(dut)
    # depth = OSD_W*OSD_H = 32; start at 30 with 4 texels -> 32,33 out of range
    payload = struct.pack("<H", 30) + bytes([0, 0, 0, 0] * 4)
    await send_frame(dut, OP_FBW, payload)
    cmd, pl = await recv_frame(dut, q)
    assert cmd == RSP_NACK and pl[0] == OP_FBW and pl[1] == 0x04, (hex(cmd), pl)


@cocotb.test()
async def test_overlay_upload(dut):
    """Upload an overlay over UART and verify it appears blended in the video."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset(dut)
    q = start_monitor(dut)

    # clear framebuffer (transparent)
    await send_frame(dut, OP_FBF, struct.pack("<HH", 0, OSD_W * OSD_H) + bytes([0, 0, 0, 0]))
    cmd, _ = await recv_frame(dut, q); assert cmd == RSP_ACK

    # upload image (addr 0, then OSD_W*OSD_H texels A,R,G,B)
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
