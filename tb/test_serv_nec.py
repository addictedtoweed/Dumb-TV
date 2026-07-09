"""cocotb testbench for the NEC IR decoder + learning demo on top_serv.

Uploads fw/nec_remote.bin, releases the core, then drives real NEC-protocol IR
frames on ir_in (time-scaled so the sim stays fast -- the firmware self-
calibrates its threshold to the measured leader, so absolute timing is
irrelevant, only the leader:0:1 ratios matter).

nec_remote.c learns the first code it decodes, then fires input_select(2) when
that same code repeats. So sending the SAME frame twice should drive mux_sel==2,
exercising the whole path: NEC waveform -> IR pin -> GPIO read -> protocol
decode -> learn/match -> command -> mux -> parser -> effect.

Run with:  make TOPLEVEL=top_serv MODULE=test_serv_nec
"""

import os
import cocotb
from cocotb.triggers import RisingEdge

from test_serv_fw import clks, upload_and_run

NEC_BIN = os.path.join(os.path.dirname(__file__), "..", "fw", "nec_remote.bin")

U = 5000        # cycles per NEC time-unit (~562.5 us, scaled down for sim speed)


async def nec_frame(dut, code32):
    """Drive one NEC frame: 16U/8U leader, 32 bits (1U mark + 1U/3U space, LSB
    first), then a stop mark. code32 bit i is sent as data bit i."""
    dut.ir_in.value = 0;  await clks(dut, 16 * U)      # leader mark
    dut.ir_in.value = 1;  await clks(dut, 8 * U)       # leader space
    for i in range(32):
        bit = (code32 >> i) & 1
        dut.ir_in.value = 0;  await clks(dut, 1 * U)               # bit mark
        dut.ir_in.value = 1;  await clks(dut, (3 if bit else 1) * U)  # space
    dut.ir_in.value = 0;  await clks(dut, 1 * U)       # stop mark
    dut.ir_in.value = 1


@cocotb.test()
async def test_nec_learn_and_match(dut):
    await upload_and_run(dut, NEC_BIN)
    await clks(dut, 150_000)               # past uart_init, into the decode loop
    assert int(dut.mux_sel.value) == 0

    CODE = 0x00FF12ED                      # arbitrary 32-bit NEC code
    await nec_frame(dut, CODE)             # first sighting -> learned
    await clks(dut, 60_000)
    await nec_frame(dut, CODE)             # repeat -> matches -> input_select(2)
    dut.ir_in.value = 1
    await clks(dut, 60_000)

    for _ in range(2_000_000):             # wait for the command frame to land
        await RisingEdge(dut.clk)
        if int(dut.mux_sel.value) == 2:
            break

    assert int(dut.mux_sel.value) == 2, (
        f"NEC learn/match did not select input 2 (mux_sel={int(dut.mux_sel.value)})")
    dut._log.info("NEC frame learned then matched -> SERV drove mux_sel=2")
