"""cocotb testbench for serv_soc (the SERV RISC-V SoC).

Loads a tiny firmware (a run of NOPs) into the host-writable program RAM while
the core is halted, releases the core, and watches the instruction bus to prove
the core comes alive and executes from host-loaded RAM (PC advances by 4 per
NOP). No RISC-V toolchain needed -- NOP is a known encoding (0x00000013).

Run with:  make TOPLEVEL=serv_soc MODULE=test_serv_soc
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

NOP = 0x00000013     # addi x0, x0, 0


async def host_write_word(dut, wordaddr, word):
    for b in range(4):
        dut.i_host_adr.value = wordaddr * 4 + b
        dut.i_host_dat.value = (word >> (8 * b)) & 0xFF
        dut.i_host_we.value = 1
        await RisingEdge(dut.clk)
    dut.i_host_we.value = 0
    await RisingEdge(dut.clk)


@cocotb.test()
async def test_core_runs(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    dut.rst.value = 1
    dut.core_halt.value = 1
    dut.ir_in.value = 1
    dut.i_host_we.value = 0
    dut.i_host_adr.value = 0
    dut.i_host_dat.value = 0
    for _ in range(8):
        await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)

    # load 64 NOPs into program RAM (core still halted)
    for w in range(64):
        await host_write_word(dut, w, NOP)

    # release the core
    dut.core_halt.value = 0

    # watch distinct instruction-fetch addresses appear on the memory bus
    seen = []
    for _ in range(20000):
        await RisingEdge(dut.clk)
        if int(dut.dbg_mem_stb.value) == 1:
            adr = int(dut.dbg_mem_adr.value)
            if not seen or adr != seen[-1]:
                seen.append(adr)
        if len(seen) >= 4:
            break

    assert len(seen) >= 3, f"core did not fetch multiple instructions: {seen}"
    # NOPs, no jumps -> PC advances by 4 each time
    assert seen[1] == seen[0] + 4 and seen[2] == seen[1] + 4, f"PC not advancing by 4: {seen}"
