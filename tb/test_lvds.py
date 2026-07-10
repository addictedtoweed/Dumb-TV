"""cocotb testbench for rgb_to_lvds -- the parallel-RGB -> FPD-Link mapper.

Verifies the 7-bit-per-lane word assembly against a Python mirror of the mapping
for every config that matters: VESA vs JEIDA packing, 24bpp vs 18bpp, and lane /
sync polarity. The high-speed 7:1 serialization + LVDS I/O are device primitives
layered on top (not simulated); this locks the logical mapping that makes one
bitstream fit many panels.

Run with:  make TOPLEVEL=rgb_to_lvds MODULE=test_lvds
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

CLK_PATTERN = 0b1100011


def expect(r, g, b, de, hs, vs, *, jeida, bpp24,
           dpol=0, cpol=0, depol=0, hspol=0, vspol=0):
    """Mirror rgb_to_lvds' mapping: return (d0, d1, d2, d3, clk_lane)."""
    if jeida:
        rc, rx = (r >> 2) & 0x3F, r & 3
        gc, gx = (g >> 2) & 0x3F, g & 3
        bc, bx = (b >> 2) & 0x3F, b & 3
    else:
        rc, rx = r & 0x3F, (r >> 6) & 3
        gc, gx = g & 0x3F, (g >> 6) & 3
        bc, bx = b & 0x3F, (b >> 6) & 3
    sde, shs, svs = de ^ depol, hs ^ hspol, vs ^ vspol

    w0 = ((gc & 1) << 6) | rc                                   # R0..R5, G0
    w1 = (((bc >> 1) & 1) << 6) | ((bc & 1) << 5) | ((gc >> 1) & 0x1F)
    w2 = (sde << 6) | (svs << 5) | (shs << 4) | ((bc >> 2) & 0xF)
    if bpp24:
        w3 = (((rx >> 1) & 1) << 6) | ((rx & 1) << 5) | \
             (((gx >> 1) & 1) << 4) | ((gx & 1) << 3) | \
             (((bx >> 1) & 1) << 2) | ((bx & 1) << 1)
    else:
        w3 = 0
    m = lambda w, p: w ^ (0x7F if p else 0)
    return (m(w0, dpol & 1), m(w1, (dpol >> 1) & 1), m(w2, (dpol >> 2) & 1),
            m(w3, (dpol >> 3) & 1), m(CLK_PATTERN, cpol))


async def apply(dut, r, g, b, de, hs, vs, cfg):
    dut.r.value, dut.g.value, dut.b.value = r, g, b
    dut.de.value, dut.hs.value, dut.vs.value = de, hs, vs
    dut.cfg_bpp24.value = cfg.get("bpp24", 1)
    dut.cfg_jeida.value = cfg.get("jeida", 0)
    dut.cfg_data_pol.value = cfg.get("dpol", 0)
    dut.cfg_clk_pol.value = cfg.get("cpol", 0)
    dut.cfg_de_pol.value = cfg.get("depol", 0)
    dut.cfg_hs_pol.value = cfg.get("hspol", 0)
    dut.cfg_vs_pol.value = cfg.get("vspol", 0)
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)                 # registered output


def check(dut, r, g, b, de, hs, vs, cfg):
    d0, d1, d2, d3, cl = expect(r, g, b, de, hs, vs,
                                jeida=cfg.get("jeida", 0), bpp24=cfg.get("bpp24", 1),
                                dpol=cfg.get("dpol", 0), cpol=cfg.get("cpol", 0),
                                depol=cfg.get("depol", 0), hspol=cfg.get("hspol", 0),
                                vspol=cfg.get("vspol", 0))
    got = (int(dut.d0.value), int(dut.d1.value), int(dut.d2.value),
           int(dut.d3.value), int(dut.clk_lane.value))
    assert got == (d0, d1, d2, d3, cl), f"cfg={cfg}: got {got} want {(d0,d1,d2,d3,cl)}"


async def reset(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    dut.rst.value = 1
    for s in ("de", "hs", "vs", "r", "g", "b", "cfg_bpp24", "cfg_jeida",
              "cfg_data_pol", "cfg_clk_pol", "cfg_de_pol", "cfg_hs_pol", "cfg_vs_pol"):
        getattr(dut, s).value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst.value = 0


VECS = [(0xB5, 0x3C, 0xE1, 1, 0, 1), (0xFF, 0x00, 0xAA, 1, 1, 0),
        (0x12, 0x34, 0x56, 0, 1, 1)]


@cocotb.test()
async def test_vesa_24bpp(dut):
    await reset(dut)
    for r, g, b, de, hs, vs in VECS:
        cfg = {"jeida": 0, "bpp24": 1}
        await apply(dut, r, g, b, de, hs, vs, cfg)
        check(dut, r, g, b, de, hs, vs, cfg)


@cocotb.test()
async def test_jeida_24bpp(dut):
    await reset(dut)
    for r, g, b, de, hs, vs in VECS:
        cfg = {"jeida": 1, "bpp24": 1}
        await apply(dut, r, g, b, de, hs, vs, cfg)
        check(dut, r, g, b, de, hs, vs, cfg)


@cocotb.test()
async def test_18bpp_d3_idle(dut):
    await reset(dut)
    r, g, b, de, hs, vs = 0xB5, 0x3C, 0xE1, 1, 0, 1
    cfg = {"jeida": 0, "bpp24": 0}
    await apply(dut, r, g, b, de, hs, vs, cfg)
    check(dut, r, g, b, de, hs, vs, cfg)
    assert int(dut.d3.value) == 0, "18bpp: D3 must be idle"


@cocotb.test()
async def test_polarity(dut):
    await reset(dut)
    r, g, b, de, hs, vs = 0xB5, 0x3C, 0xE1, 1, 0, 1
    cfg = {"jeida": 0, "bpp24": 1, "dpol": 0b1010, "cpol": 1,
           "depol": 1, "hspol": 1, "vspol": 1}
    await apply(dut, r, g, b, de, hs, vs, cfg)
    check(dut, r, g, b, de, hs, vs, cfg)
    # a fully-inverted clock lane is the pattern's complement
    assert int(dut.clk_lane.value) == (CLK_PATTERN ^ 0x7F)
