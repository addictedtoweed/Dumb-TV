"""cocotb testbench for the IR-remote demo on top_serv.

Uploads the compiled IR decoder (fw/ir_remote.bin), releases the core, then
drives a synthetic consumer-IR press on the ir_in pin and proves the running
RISC-V core reads the IR input, decodes it, and issues the mapped TV command.

ir_remote.c counts the number of IR bursts (falling edges) in a press and does
input_select(count). So driving 2 bursts should make mux_sel == 2 -- exercising
the full IR path: IR pin -> GPIO read -> firmware decode -> command frame ->
internal uart_rx -> mux -> parser -> effect.

Run with:  make TOPLEVEL=top_serv MODULE=test_serv_ir
"""

import os
import cocotb
from cocotb.triggers import RisingEdge

# reuse the framing/upload helpers from the firmware demo
from test_serv_fw import clks, upload_and_run

IR_BIN = os.path.join(os.path.dirname(__file__), "..", "fw", "ir_remote.bin")


async def ir_burst(dut, n, mark=4000, space=4000):
    """Drive n IR bursts: each is `mark` cycles active-low then `space` idle-high.
    Widths are well above the firmware's sample period so every edge is seen and
    the inter-burst gaps don't look like end-of-press."""
    for _ in range(n):
        dut.ir_in.value = 0
        await clks(dut, mark)
        dut.ir_in.value = 1
        await clks(dut, space)


@cocotb.test()
async def test_ir_press_selects_input(dut):
    await upload_and_run(dut, IR_BIN)

    # let the firmware get past uart_init and into its IR poll loop
    await clks(dut, 150_000)
    assert int(dut.mux_sel.value) == 0

    await ir_burst(dut, 2)                 # a 2-burst press -> input 2
    dut.ir_in.value = 1
    await clks(dut, 250_000)               # long idle ends the press

    for _ in range(2_000_000):             # wait for the command frame to land
        await RisingEdge(dut.clk)
        if int(dut.mux_sel.value) == 2:
            break

    assert int(dut.mux_sel.value) == 2, (
        f"IR press did not select input 2 (mux_sel={int(dut.mux_sel.value)}) -- "
        f"check DUMBTV_IR_GAP vs the driven burst/gap widths")
    dut._log.info("IR 2-burst press -> SERV decoded -> mux_sel=2")
