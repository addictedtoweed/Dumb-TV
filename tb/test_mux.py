"""cocotb testbench for the two-source command mux (top_mux).

Two independent UART links (host = rx0/tx0, internal/SERV = rx1/tx1) share one
cmd_parser via cmd_mux. Verifies each link gets its own responses, a command's
effect is observable (mux_sel), and concurrent frames from both links are
serialized frame-atomically with responses routed to the right requester.

Run with:  make TOPLEVEL=top_mux MODULE=test_mux
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
    dut.rx0.value = 1
    dut.rx1.value = 1
    dut.fw_raddr.value = 0
    dut.rst.value = 1
    await clks(dut, 20)
    dut.rst.value = 0
    await clks(dut, 5)


async def fw_read(dut, addr):
    dut.fw_raddr.value = addr
    await clks(dut, 2)             # 1-clock RAM read + margin
    return int(dut.fw_rdata.value)


@cocotb.test()
async def test_firmware_upload(dut):
    """FW_HALT/FW_WRITE/FW_START: core held in reset, blob lands in RAM, core
    released to run."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset(dut)
    q0 = start_monitor(dut, dut.tx0)

    assert int(dut.core_rst.value) == 1, "core should be held after reset"

    await send_frame(dut, dut.rx0, OP_FWHALT)
    cmd, _ = await recv_frame(dut, q0); assert cmd == RSP_ACK
    assert int(dut.core_rst.value) == 1

    blob = bytes([0x13, 0x00, 0x00, 0x00, 0x93, 0x00, 0x10, 0x00, 0xEF, 0xBE, 0xAD, 0xDE])
    await send_frame(dut, dut.rx0, OP_FW, struct.pack("<H", 0) + blob)
    cmd, _ = await recv_frame(dut, q0); assert cmd == RSP_ACK
    # also write a chunk at a non-zero address
    blob2 = bytes([0xCA, 0xFE, 0x12, 0x34])
    await send_frame(dut, dut.rx0, OP_FW, struct.pack("<H", 100) + blob2)
    cmd, _ = await recv_frame(dut, q0); assert cmd == RSP_ACK

    for i, b in enumerate(blob):
        assert await fw_read(dut, i) == b, f"fw[{i}] wrong"
    for i, b in enumerate(blob2):
        assert await fw_read(dut, 100 + i) == b, f"fw[{100+i}] wrong"

    await send_frame(dut, dut.rx0, OP_FWSTART)
    cmd, _ = await recv_frame(dut, q0); assert cmd == RSP_ACK
    await clks(dut, 3)
    assert int(dut.core_rst.value) == 0, "core should run after FW_START"


@cocotb.test()
async def test_firmware_range(dut):
    """FW_WRITE past the 16 KB RAM end returns NACK(range)."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset(dut)
    q0 = start_monitor(dut, dut.tx0)
    await send_frame(dut, dut.rx0, OP_FW, struct.pack("<H", 16383) + bytes([1, 2, 3]))
    cmd, pl = await recv_frame(dut, q0)
    assert cmd == RSP_NACK and pl[0] == OP_FW and pl[1] == 0x04, (hex(cmd), pl)


@cocotb.test()
async def test_host_ping(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset(dut)
    q0 = start_monitor(dut, dut.tx0)
    await send_frame(dut, dut.rx0, OP_PING)
    cmd, pl = await recv_frame(dut, q0)
    assert cmd == RSP_ACK and pl == bytes([OP_PING]), (hex(cmd), pl)


@cocotb.test()
async def test_internal_ping(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset(dut)
    q1 = start_monitor(dut, dut.tx1)
    await send_frame(dut, dut.rx1, OP_PING)
    cmd, pl = await recv_frame(dut, q1)
    assert cmd == RSP_ACK and pl == bytes([OP_PING]), (hex(cmd), pl)


@cocotb.test()
async def test_internal_command_effect(dut):
    """A command from the internal link actually acts (mux_sel changes)."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset(dut)
    q1 = start_monitor(dut, dut.tx1)
    await send_frame(dut, dut.rx1, OP_MUXSEL, bytes([5]))
    cmd, _ = await recv_frame(dut, q1); assert cmd == RSP_ACK
    await clks(dut, 5)
    assert int(dut.mux_sel.value) == 5, hex(int(dut.mux_sel.value))


@cocotb.test()
async def test_concurrent(dut):
    """Both links send at the same time -> both get their own ACK, on the right
    TX line, frame-atomically serialized."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset(dut)
    q0 = start_monitor(dut, dut.tx0)
    q1 = start_monitor(dut, dut.tx1)

    a = cocotb.start_soon(send_frame(dut, dut.rx0, OP_PING))
    b = cocotb.start_soon(send_frame(dut, dut.rx1, OP_MUXSEL, bytes([7])))
    await a
    await b

    c0, p0 = await recv_frame(dut, q0)
    assert c0 == RSP_ACK and p0 == bytes([OP_PING]), (hex(c0), p0)
    c1, p1 = await recv_frame(dut, q1)
    assert c1 == RSP_ACK and p1 == bytes([OP_MUXSEL]), (hex(c1), p1)
    await clks(dut, 5)
    assert int(dut.mux_sel.value) == 7
