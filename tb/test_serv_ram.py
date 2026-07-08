"""cocotb testbench for serv_ram_hw (host-writable Wishbone program RAM).

Drives the Wishbone port as a master and the host byte-write port, verifying
host-loaded firmware reads back over Wishbone and that Wishbone writes round-trip.

Run with:  make TOPLEVEL=serv_ram_hw MODULE=test_serv_ram
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge


async def reset(dut):
    dut.i_wb_rst.value = 1
    dut.i_wb_cyc.value = 0
    dut.i_wb_we.value = 0
    dut.i_wb_sel.value = 0
    dut.i_wb_adr.value = 0
    dut.i_wb_dat.value = 0
    dut.i_host_we.value = 0
    dut.i_host_adr.value = 0
    dut.i_host_dat.value = 0
    for _ in range(5):
        await RisingEdge(dut.i_wb_clk)
    dut.i_wb_rst.value = 0
    await RisingEdge(dut.i_wb_clk)


async def host_write(dut, byteaddr, byte):
    dut.i_host_adr.value = byteaddr
    dut.i_host_dat.value = byte
    dut.i_host_we.value = 1
    await RisingEdge(dut.i_wb_clk)
    dut.i_host_we.value = 0
    await RisingEdge(dut.i_wb_clk)


async def wb_read(dut, byteaddr):
    dut.i_wb_adr.value = byteaddr >> 2
    dut.i_wb_sel.value = 0xF
    dut.i_wb_we.value = 0
    dut.i_wb_cyc.value = 1
    await RisingEdge(dut.i_wb_clk)
    while int(dut.o_wb_ack.value) == 0:
        await RisingEdge(dut.i_wb_clk)
    val = int(dut.o_wb_rdt.value)
    dut.i_wb_cyc.value = 0
    await RisingEdge(dut.i_wb_clk)
    return val


async def wb_write(dut, byteaddr, word, sel=0xF):
    dut.i_wb_adr.value = byteaddr >> 2
    dut.i_wb_dat.value = word
    dut.i_wb_sel.value = sel
    dut.i_wb_we.value = 1
    dut.i_wb_cyc.value = 1
    await RisingEdge(dut.i_wb_clk)
    while int(dut.o_wb_ack.value) == 0:
        await RisingEdge(dut.i_wb_clk)
    dut.i_wb_cyc.value = 0
    dut.i_wb_we.value = 0
    await RisingEdge(dut.i_wb_clk)


def word_bytes(word):
    return [(word >> (8 * i)) & 0xFF for i in range(4)]      # little-endian


@cocotb.test()
async def test_host_load_then_wb_read(dut):
    """Firmware loaded through the host port reads back over Wishbone."""
    cocotb.start_soon(Clock(dut.i_wb_clk, 10, units="ns").start())
    await reset(dut)

    blob = [0x00000013, 0x00100093, 0xDEADBEEF, 0x12345678]   # words at addr 0,4,8,12
    for w, word in enumerate(blob):
        for b, byte in enumerate(word_bytes(word)):
            await host_write(dut, w * 4 + b, byte)

    for w, word in enumerate(blob):
        rd = await wb_read(dut, w * 4)
        assert rd == word, f"word {w}: {rd:#010x} != {word:#010x}"


@cocotb.test()
async def test_wb_roundtrip(dut):
    """Wishbone writes (with byte selects) round-trip through Wishbone reads."""
    cocotb.start_soon(Clock(dut.i_wb_clk, 10, units="ns").start())
    await reset(dut)

    await wb_write(dut, 0x20, 0xCAFEF00D)
    assert await wb_read(dut, 0x20) == 0xCAFEF00D

    # byte-select write: only low byte
    await wb_write(dut, 0x20, 0x000000AA, sel=0x1)
    assert await wb_read(dut, 0x20) == 0xCAFEF0AA
