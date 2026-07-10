"""cocotb testbench for top_lvds -- the OUTPUT=lvds seam end to end.

Sends the LVDS command over the UART, then checks the native-LVDS lane words the
compositor's RGB produces through rgb_to_lvds match the configured mapping
(default 24bpp/VESA, and a JEIDA + polarity config sent over serial). Reuses the
mapping mirror from test_lvds. This exercises: UART -> cmd_parser -> ctrl_regs
(lvds_cfg) -> rgb_to_lvds -> lane words.

Run with:  make TOPLEVEL=top_lvds MODULE=test_lvds_top
"""

import struct
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

from test_lvds import expect, CLK_PATTERN

CLKS_PER_BIT = 8
SYNC = 0xA5
OP_LVDS = 0x60


def crc8(data):
    c = 0
    for byte in data:
        c ^= byte
        for _ in range(8):
            c = ((c << 1) ^ 0x07) & 0xFF if (c & 0x80) else (c << 1) & 0xFF
    return c


def frame(cmd, payload=b""):
    body = bytes([cmd]) + struct.pack("<H", len(payload)) + payload
    return bytes([SYNC]) + body + bytes([crc8(body)])


async def clks(dut, n):
    for _ in range(n):
        await RisingEdge(dut.clk)


async def send_frame(dut, cmd, payload=b""):
    for byte in frame(cmd, payload):
        dut.rx.value = 0
        await clks(dut, CLKS_PER_BIT)
        for i in range(8):
            dut.rx.value = (byte >> i) & 1
            await clks(dut, CLKS_PER_BIT)
        dut.rx.value = 1
        await clks(dut, CLKS_PER_BIT * 2)


def unpack(cfg):
    return dict(bpp24=cfg & 1, jeida=(cfg >> 1) & 1, cpol=(cfg >> 2) & 1,
                depol=(cfg >> 3) & 1, hspol=(cfg >> 4) & 1, vspol=(cfg >> 5) & 1,
                dpol=(cfg >> 6) & 0xF)


async def check_mapping(dut, cfg, n=24):
    """Sample n cycles: the LVDS words (t+1) must equal the mapping of the RGB
    fed in (t)."""
    kw = unpack(cfg)
    for _ in range(n):
        await RisingEdge(dut.clk)
        r, g, b = int(dut.out_r.value), int(dut.out_g.value), int(dut.out_b.value)
        de, hs, vs = int(dut.out_de.value), int(dut.out_hsync.value), int(dut.out_vsync.value)
        await RisingEdge(dut.clk)
        got = (int(dut.lvds_d0.value), int(dut.lvds_d1.value), int(dut.lvds_d2.value),
               int(dut.lvds_d3.value), int(dut.lvds_clk.value))
        want = expect(r, g, b, de, hs, vs, **kw)
        assert got == want, f"cfg={cfg:#06x} rgb=({r},{g},{b}) got {got} want {want}"


async def reset(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    dut.rx.value = 1
    dut.rst.value = 1
    await clks(dut, 20)
    dut.rst.value = 0
    await clks(dut, 5)


@cocotb.test()
async def test_default_vesa_24bpp(dut):
    """Reset default lvds_cfg = 0x0001 (24bpp, VESA, no inversion)."""
    await reset(dut)
    await check_mapping(dut, 0x0001)


@cocotb.test()
async def test_lvds_command_jeida_pol(dut):
    """Send LVDS over UART: JEIDA, data_pol=1010, clk+sync inverted -> the lane
    words follow the new mapping."""
    await reset(dut)
    cfg = 0x0001 | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4) | (1 << 5) | (0b1010 << 6)
    await send_frame(dut, OP_LVDS, struct.pack("<H", cfg))
    await clks(dut, 40)                     # let the ACK finish / cfg settle
    await check_mapping(dut, cfg)


@cocotb.test()
async def test_lvds_18bpp(dut):
    """18bpp: D3 idles (before polarity)."""
    await reset(dut)
    cfg = 0x0000                            # bpp24=0, VESA, no pol
    await send_frame(dut, OP_LVDS, struct.pack("<H", cfg))
    await clks(dut, 40)
    await check_mapping(dut, cfg)
