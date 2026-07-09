"""cocotb testbench for the SERV firmware demo on top_serv.

Uploads the REAL compiled firmware (fw/firmware.bin) over the host serial
protocol, releases the core, and proves the running RISC-V core drives the TV:
the firmware bit-bangs a command frame out its GPIO, the FPGA feeds it into the
parser as the internal source, and the command takes effect (mux_sel changes).

test_calibrate measures the core's bit-bang timing (min q pulse width in clk
cycles) so INT_CLKS_PER_BIT in top_serv can be matched to it -- run it, read the
printed period, set the param, then test_fw_drives_mux asserts.

Run with:  make TOPLEVEL=top_serv MODULE=test_serv_fw
"""

import os
import struct
from collections import deque
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time

SYNC = 0xA5
OP_MUXSEL = 0x40
OP_FWHALT, OP_FW, OP_FWSTART = 0x50, 0x51, 0x52
RSP_ACK = 0x80
CLKS_PER_BIT = 8

FW_BIN = os.path.join(os.path.dirname(__file__), "..", "fw", "firmware.bin")


def crc8(data: bytes) -> int:
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


async def send_byte(dut, val):
    dut.rx.value = 0
    await clks(dut, CLKS_PER_BIT)
    for i in range(8):
        dut.rx.value = (val >> i) & 1
        await clks(dut, CLKS_PER_BIT)
    dut.rx.value = 1
    await clks(dut, CLKS_PER_BIT * 2)


async def send_frame(dut, cmd, payload=b""):
    for b in frame(cmd, payload):
        await send_byte(dut, b)


# ---- robust async TX monitor (won't hang: reads whatever tx emits) --------
async def _recv_byte(dut):
    sig = dut.tx
    while int(sig.value) == 1:
        await RisingEdge(dut.clk)
    await clks(dut, CLKS_PER_BIT + CLKS_PER_BIT // 2)
    val = 0
    for i in range(8):
        val |= (int(sig.value) & 1) << i
        await clks(dut, CLKS_PER_BIT)
    return val


async def _monitor(dut, q):
    while True:
        q.append(await _recv_byte(dut))


async def get_byte(dut, q):
    while not q:
        await RisingEdge(dut.clk)
    return q.popleft()


async def recv_ack(dut, q):
    sync = await get_byte(dut, q)
    assert sync == SYNC, f"bad sync 0x{sync:02x}"
    cmd = await get_byte(dut, q)
    lo = await get_byte(dut, q)
    hi = await get_byte(dut, q)
    length = lo | (hi << 8)
    payload = bytes([await get_byte(dut, q) for _ in range(length)])
    await get_byte(dut, q)                      # crc
    assert cmd == RSP_ACK, f"expected ACK, got 0x{cmd:02x} payload={payload!r}"
    return payload


async def upload_and_run(dut, fw_bin=FW_BIN):
    """Reset, upload a firmware .bin over the host link (reading each ACK so the
    host paces itself -- unpaced uploads desync the parser and never clear
    core_halt), release the core."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    dut.rx.value = 1
    dut.ir_in.value = 1           # IR receiver idles high
    dut.rst.value = 1
    await clks(dut, 20)
    dut.rst.value = 0
    await clks(dut, 5)
    q = deque()
    cocotb.start_soon(_monitor(dut, q))

    if not os.path.exists(fw_bin) or os.path.getsize(fw_bin) == 0:
        raise cocotb.result.SkipTest(f"{fw_bin} missing -- run fw/build.sh")
    with open(fw_bin, "rb") as f:
        blob = f.read()

    await send_frame(dut, OP_FWHALT);  await recv_ack(dut, q)
    for off in range(0, len(blob), 256):
        chunk = blob[off:off + 256]
        await send_frame(dut, OP_FW, struct.pack("<H", off) + chunk)
        await recv_ack(dut, q)
    await send_frame(dut, OP_FWSTART);  await recv_ack(dut, q)
    await clks(dut, 5)
    return len(blob)


@cocotb.test(skip=not os.environ.get("DUMBTV_CALIBRATE"))
async def test_calibrate(dut):
    """Measure the core's bit-bang timing: minimum q pulse width in clk cycles
    ~= one UART bit period. Set INT_CLKS_PER_BIT to this. Opt-in (slow): run with
    DUMBTV_CALIBRATE=1 when re-tuning for a new clock / DUMBTV_BIT_LOOPS."""
    n = await upload_and_run(dut)
    dut._log.info(f"firmware {n} bytes loaded; core released, watching q...")

    prev = int(dut.serv_q.value)
    last_edge = None
    widths = []
    edges = 0
    for _ in range(4_000_000):
        await RisingEdge(dut.clk)
        v = int(dut.serv_q.value)
        if v != prev:
            t = get_sim_time("ns") / 10.0
            if last_edge is not None:
                widths.append(t - last_edge)
            last_edge = t
            prev = v
            edges += 1
            if edges >= 40:
                break

    assert widths, "q never toggled -- firmware didn't bit-bang"
    unit = min(widths)
    dut._log.info(f"q edges={edges} widths(cyc)={[round(w) for w in widths[:20]]}")
    dut._log.info(f">>> min pulse (1 bit) ~= {round(unit)} clk cycles; "
                  f"set INT_CLKS_PER_BIT to this")


@cocotb.test()
async def test_fw_drives_mux(dut):
    """The running RISC-V core drives the TV: example.c does input_select(1), so
    after the core bit-bangs its frame through the internal link, mux_sel becomes
    1 -- proving firmware -> GPIO -> internal uart_rx -> mux -> parser -> effect.

    Requires INT_CLKS_PER_BIT in top_serv to match the firmware bit period."""
    await upload_and_run(dut)
    assert int(dut.mux_sel.value) == 0, "mux_sel should start at 0"

    for _ in range(3_000_000):
        await RisingEdge(dut.clk)
        if int(dut.mux_sel.value) == 1:
            break

    assert int(dut.mux_sel.value) == 1, (
        f"SERV firmware never drove mux_sel to 1 (got {int(dut.mux_sel.value)}) "
        f"-- check INT_CLKS_PER_BIT vs bit period")
    dut._log.info("SERV core drove mux_sel=1 via a bit-banged command frame")
