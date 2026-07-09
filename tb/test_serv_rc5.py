"""cocotb testbench for the RC5 (Manchester) IR decoder + learning on top_serv.

Drives real RC5 bi-phase frames on ir_in (time-scaled for sim speed) and proves
the running core decodes Manchester, learns the first code, and matches its
repeat -> mux_sel==2. Convention: '1' = low T then high T (rising mid-edge),
'0' = high T then low T; idle high; frame opens with a '1' start bit.

Run with:  make TOPLEVEL=top_serv MODULE=test_serv_rc5
"""

import os
import cocotb
from cocotb.triggers import RisingEdge

from test_serv_fw import clks, upload_and_run

RC5_BIN = os.path.join(os.path.dirname(__file__), "..", "fw", "rc5_remote.bin")

T = 6000        # cycles per half-bit (~889 us, scaled for sim speed)


async def rc5_frame(dut, bits14):
    """Drive one 14-bit RC5 frame, MSB (bit 0) first. bit 0 must be 1 (start)."""
    for k in range(14):
        bit = (bits14 >> (13 - k)) & 1
        if bit:                                 # '1' = low then high
            dut.ir_in.value = 0;  await clks(dut, T)
            dut.ir_in.value = 1;  await clks(dut, T)
        else:                                   # '0' = high then low
            dut.ir_in.value = 1;  await clks(dut, T)
            dut.ir_in.value = 0;  await clks(dut, T)
    dut.ir_in.value = 1                          # idle


@cocotb.test()
async def test_rc5_learn_and_match(dut):
    await upload_and_run(dut, RC5_BIN)
    await clks(dut, 150_000)               # past uart_init, into the decode loop
    assert int(dut.mux_sel.value) == 0

    CODE = 0b10_1110_1100_1101             # 14 bits, bit0(MSB)=1 start bit
    await rc5_frame(dut, CODE)             # first -> learned
    await clks(dut, 60_000)
    await rc5_frame(dut, CODE)             # repeat -> matched -> input_select(2)
    dut.ir_in.value = 1
    await clks(dut, 60_000)

    for _ in range(2_000_000):
        await RisingEdge(dut.clk)
        if int(dut.mux_sel.value) == 2:
            break

    assert int(dut.mux_sel.value) == 2, (
        f"RC5 learn/match did not select input 2 (mux_sel={int(dut.mux_sel.value)})")
    dut._log.info("RC5 Manchester frame learned then matched -> mux_sel=2")
