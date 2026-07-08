"""cocotb testbench for top_serv -- the host UART + on-board SERV core sharing
one cmd_parser via cmd_mux.

Proves the full internal-brains loop end-to-end:
  * the host link still works through the combined top (PING, a command effect);
  * firmware uploaded over the REAL host serial protocol (FW_HALT/FW_WRITE/
    FW_START) lands in the SERV core's program RAM and the released core executes
    it (PC advances). No RISC-V toolchain needed here -- NOP is a known encoding;
    a real bit-banging firmware (which would drive commands back in on source 1)
    is the next step and needs riscv32-gcc.

Run with:  make TOPLEVEL=top_serv MODULE=test_serv
"""

import struct
from collections import deque
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

CLKS_PER_BIT = 8
SYNC = 0xA5
OP_PING, OP_MUXSEL = 0x01, 0x40
OP_FWHALT, OP_FW, OP_FWSTART = 0x50, 0x51, 0x52
RSP_ACK, RSP_NACK = 0x80, 0x81
NOP = 0x00000013


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


async def send_byte(dut, sig, val):
    sig.value = 0
    await clks(dut, CLKS_PER_BIT)
    for i in range(8):
        sig.value = (val >> i) & 1
        await clks(dut, CLKS_PER_BIT)
    sig.value = 1
    await clks(dut, CLKS_PER_BIT)
    await clks(dut, CLKS_PER_BIT)


async def send_frame(dut, sig, cmd, payload=b""):
    for b in frame(cmd, payload):
        await send_byte(dut, sig, b)


async def recv_byte(dut, sig):
    while int(sig.value) == 1:
        await RisingEdge(dut.clk)
    await clks(dut, CLKS_PER_BIT + CLKS_PER_BIT // 2)
    val = 0
    for i in range(8):
        val |= (int(sig.value) & 1) << i
        await clks(dut, CLKS_PER_BIT)
    return val


async def _monitor(dut, sig, q):
    while True:
        q.append(await recv_byte(dut, sig))


def start_monitor(dut, sig):
    q = deque()
    cocotb.start_soon(_monitor(dut, sig, q))
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
    await clks(dut, 20)
    dut.rst.value = 0
    await clks(dut, 5)


@cocotb.test()
async def test_host_still_works(dut):
    """The host link works through the combined SERV top: PING acks, and a
    command actually acts (mux_sel changes)."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset(dut)
    q = start_monitor(dut, dut.tx)

    await send_frame(dut, dut.rx, OP_PING)
    cmd, pl = await recv_frame(dut, q)
    assert cmd == RSP_ACK and pl == bytes([OP_PING]), (hex(cmd), pl)

    await send_frame(dut, dut.rx, OP_MUXSEL, bytes([6]))
    cmd, _ = await recv_frame(dut, q); assert cmd == RSP_ACK
    await clks(dut, 5)
    assert int(dut.mux_sel.value) == 6, hex(int(dut.mux_sel.value))


@cocotb.test()
async def test_upload_and_run(dut):
    """Upload firmware over the real host serial protocol, then watch the SERV
    core execute it.

    FW_HALT (hold core) -> FW_WRITE a run of NOPs into program RAM -> FW_START
    (release). The core should fetch from host-loaded RAM and its PC advance by 4
    per NOP -- proving host serial -> parser -> SERV RAM -> running core.
    """
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset(dut)
    q = start_monitor(dut, dut.tx)

    assert int(dut.core_rst.value) == 1, "core should be held after reset"

    await send_frame(dut, dut.rx, OP_FWHALT)
    cmd, _ = await recv_frame(dut, q); assert cmd == RSP_ACK
    assert int(dut.core_rst.value) == 1

    # 64 NOPs, uploaded as one FW_WRITE at address 0
    blob = struct.pack("<64I", *([NOP] * 64))
    await send_frame(dut, dut.rx, OP_FW, struct.pack("<H", 0) + blob)
    cmd, _ = await recv_frame(dut, q); assert cmd == RSP_ACK

    await send_frame(dut, dut.rx, OP_FWSTART)
    cmd, _ = await recv_frame(dut, q); assert cmd == RSP_ACK
    await clks(dut, 3)
    assert int(dut.core_rst.value) == 0, "core should run after FW_START"

    # watch the instruction bus: distinct fetch addresses, advancing by 4
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
    assert seen[1] == seen[0] + 4 and seen[2] == seen[1] + 4, \
        f"PC not advancing by 4: {seen}"
