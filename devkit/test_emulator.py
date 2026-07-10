"""Headless regression for the dev-kit RISC-V emulator (Phase B).

Runs the actual fw/*.bin on the pure-Python RV32I core and checks the whole
internal-processor path end to end:
  * firmware.bin bit-bangs OSD commands  -> mux_sel / backlight change
  * nec_remote.bin / rc5_remote.bin decode a keyboard-synthesized remote,
    learn the first code, and act on its repeat -> input_select(2)

    python devkit/test_emulator.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from dumbtv_sim import OsdModel, Device                                  # noqa: E402
from dumbtv_sim.riscv import RV32                                        # noqa: E402
from dumbtv_sim.ir import IrSource                                       # noqa: E402

FW = os.path.join(os.path.dirname(__file__), "..", "fw")


def _cpu(binname, ir=None):
    osd = OsdModel()
    dev = Device(osd)
    cpu = RV32(dev, ir_source=ir)
    with open(os.path.join(FW, binname), "rb") as f:
        cpu.load(f.read())
    return osd, cpu


def test_firmware_drives_osd():
    osd, cpu = _cpu("firmware.bin")
    cpu.run(400_000)
    assert osd.mux_sel == 1, osd.mux_sel
    assert osd.backlight == 200, osd.backlight
    print(f"firmware.bin -> mux_sel={osd.mux_sel} backlight={osd.backlight}  OK")


def _learn_match(binname, send, code, runs=300_000):
    ir = IrSource()
    osd, cpu = _cpu(binname, ir)
    cpu.run(30_000)                     # uart_init + reach the IR wait loop
    send(ir, code, cpu.icount); cpu.run(runs)      # learn
    send(ir, code, cpu.icount); cpu.run(runs)      # match -> input_select(2)
    return osd.mux_sel


def test_nec_learn():
    sel = _learn_match("nec_remote.bin",
                       lambda ir, c, t: ir.send_nec(c, t), 0x00FF12ED)
    assert sel == 2, sel
    print(f"nec_remote.bin learn+match -> mux_sel={sel}  OK")


def test_rc5_learn():
    sel = _learn_match("rc5_remote.bin",
                       lambda ir, c, t: ir.send_rc5(c, t, U=80), 0b10_1110_1100_1101)
    assert sel == 2, sel
    print(f"rc5_remote.bin learn+match -> mux_sel={sel}  OK")


def test_learn_wizard():
    """Autonomous multi-button wizard: learn 4 buttons, then a learned press
    fires its mapped action and an unlearned one is ignored."""
    from dumbtv_sim.ir import IrSource
    ir = IrSource()
    osd, cpu = _cpu("learn_remote.bin", ir)
    codes = [0x00FF11EE, 0x00FF22DD, 0x00FF33CC, 0x00FF44BB]
    cpu.run(200_000)                    # boot: prompts, reach the first wait
    for c in codes:                     # learn phase
        ir.send_nec(c, cpu.icount); cpu.run(300_000)
    ir.send_nec(codes[2], cpu.icount); cpu.run(300_000)   # -> input_select(3)
    assert osd.mux_sel == 3, osd.mux_sel
    ir.send_nec(0x00FF7788, cpu.icount); cpu.run(300_000)  # unlearned -> ignored
    assert osd.mux_sel == 3, osd.mux_sel
    print(f"learn_remote.bin: bound 4, matched code[2] -> input {osd.mux_sel}, "
          f"unlearned ignored  OK")


if __name__ == "__main__":
    test_firmware_drives_osd()
    test_nec_learn()
    test_rc5_learn()
    test_learn_wizard()
    print("all emulator checks passed")
