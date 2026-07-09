"""dumbtv_sim.riscv -- a small pure-Python RV32I emulator for the on-board core.

Runs the actual firmware built in fw/ (the same .bin the FPGA's SERV core runs),
modelling the Servant memory map:

    RAM   @ 0x00000000
    GPIO  @ 0x40000000   write bit 0 = the bit-banged UART out (-> OSD commands)
                         read  bit 0 = the IR receiver input (<- keyboard codes)
    TIMER @ 0x80000000   (mtime; firmware here doesn't use it)

The GPIO-out line is a bit-banged UART; a decoder reconstructs the bytes (timing
in instruction-count, auto-calibrated from the first start bit) and feeds them to
the same Device the host serial link uses -- so the running firmware drives the
OSD. The GPIO-in line is driven by an IrSource (keyboard-synthesized NEC/RC5) so
the remote-learning firmware can be exercised. This is a functional model, not
cycle-accurate.
"""

GPIO_ADDR = 0x40000000
TIMER_BASE = 0x80000000


def _sx(val, bits):
    m = 1 << (bits - 1)
    return (val ^ m) - m


class _Uart:
    """Decode the bit-banged GPIO-out line into bytes. Timing is in instruction
    count, auto-calibrated (bit period T) from the first low pulse -- a start
    bit, which for 0xA5 is exactly one bit wide.

    Decoding is by EDGE INTERVALS: each same-level run is quantised to round(dt/T)
    bits and the decoder re-syncs on every edge. That tolerates the per-bit jitter
    of the bit-serial firmware (~+-9%) where fixed-offset sampling would drift and
    corrupt a byte."""

    def __init__(self, on_byte):
        self.on_byte = on_byte
        self.times = [0]
        self.levels = [1]                 # idle high
        self.T = None
        self.cidx = 1                     # next transition index to examine

    def transition(self, t, level):
        self.times.append(t)
        self.levels.append(level)

    def poll(self, now):
        if self.T is None:                # calibrate: first high->low->high
            for i in range(1, len(self.levels)):
                if self.levels[i] == 0 and self.levels[i - 1] == 1:
                    for k in range(i + 1, len(self.levels)):
                        if self.levels[k] == 1:
                            self.T = self.times[k] - self.times[i]
                            break
                    break
            if not self.T:
                return
        T = self.T
        while True:
            # next falling edge (start bit) at/after the cursor
            i = None
            for idx in range(max(1, self.cidx), len(self.levels)):
                if self.levels[idx] == 0 and self.levels[idx - 1] == 1:
                    i = idx
                    break
            if i is None:
                self.cidx = len(self.levels)
                break
            t0 = self.times[i]
            if now < t0 + 10 * T:         # wait until the whole byte has elapsed
                self.cidx = i
                break
            # reconstruct 10 bits (start + 8 data + stop) from run lengths
            bits = []
            level = 0
            pos = t0
            j = i + 1
            while len(bits) < 10 and j < len(self.times):
                nb = max(1, round((self.times[j] - pos) / T))
                bits.extend([level] * nb)
                level = self.levels[j]
                pos = self.times[j]
                j += 1
            if len(bits) < 10:            # trailing stop/idle (no transition)
                bits.extend([level] * (10 - len(bits)))
            byte = sum((bits[1 + b] & 1) << b for b in range(8))
            self.on_byte(byte)
            # the run terminator we just consumed may itself be the next byte's
            # start edge (stop bit merges with it), so step back one transition.
            self.cidx = max(i + 1, j - 1)


class RV32:
    def __init__(self, device, ir_source=None, ram_size=1 << 16):
        self.dev = device
        self.ir = ir_source
        self.ram = bytearray(ram_size)
        self.x = [0] * 32
        self.pc = 0
        self.icount = 0
        self.gpio_out = 1
        self.halted = False
        self.uart = _Uart(lambda byte: self.dev.feed(bytes([byte])))

    def load(self, blob, addr=0):
        self.ram[addr:addr + len(blob)] = blob

    def reset(self):
        self.x = [0] * 32
        self.pc = 0
        self.icount = 0

    # ---- memory / MMIO ----
    def _load(self, addr, size, signed):
        if addr >= GPIO_ADDR:
            if addr < TIMER_BASE:                       # GPIO read = IR line
                v = self.ir.level(self.icount) if self.ir else 1
                return v & 1
            return self.icount & 0xFFFFFFFF              # timer mtime proxy
        a = addr & 0xFFFF
        v = int.from_bytes(self.ram[a:a + size], "little")
        return _sx(v, size * 8) & 0xFFFFFFFF if signed else v

    def _store(self, addr, size, val):
        if addr >= GPIO_ADDR:
            if addr < TIMER_BASE:                       # GPIO write = UART out
                lvl = val & 1
                if lvl != self.gpio_out:
                    self.gpio_out = lvl
                    self.uart.transition(self.icount, lvl)
            return
        a = addr & 0xFFFF
        self.ram[a:a + size] = (val & ((1 << (size * 8)) - 1)).to_bytes(size, "little")

    # ---- one instruction ----
    def step(self):
        x = self.x
        pc = self.pc
        ins = int.from_bytes(self.ram[pc & 0xFFFF:(pc & 0xFFFF) + 4], "little")
        op = ins & 0x7F
        rd = (ins >> 7) & 0x1F
        f3 = (ins >> 12) & 7
        rs1 = (ins >> 15) & 0x1F
        rs2 = (ins >> 20) & 0x1F
        f7 = (ins >> 25) & 0x7F
        npc = (pc + 4) & 0xFFFFFFFF

        if op == 0x37:                                  # LUI
            x[rd] = ins & 0xFFFFF000
        elif op == 0x17:                                # AUIPC
            x[rd] = (pc + (ins & 0xFFFFF000)) & 0xFFFFFFFF
        elif op == 0x6F:                                # JAL
            imm = _sx(((ins >> 31) << 20) | (((ins >> 21) & 0x3FF) << 1) |
                      (((ins >> 20) & 1) << 11) | (((ins >> 12) & 0xFF) << 12), 21)
            x[rd] = npc
            npc = (pc + imm) & 0xFFFFFFFF
        elif op == 0x67:                                # JALR
            imm = _sx(ins >> 20, 12)
            t = npc
            npc = (x[rs1] + imm) & 0xFFFFFFFE
            x[rd] = t
        elif op == 0x63:                                # branches
            imm = _sx(((ins >> 31) << 12) | (((ins >> 25) & 0x3F) << 5) |
                      (((ins >> 8) & 0xF) << 1) | (((ins >> 7) & 1) << 11), 13)
            a, b = x[rs1], x[rs2]
            sa, sb = _sx(a, 32), _sx(b, 32)
            take = (f3 == 0 and a == b) or (f3 == 1 and a != b) or \
                   (f3 == 4 and sa < sb) or (f3 == 5 and sa >= sb) or \
                   (f3 == 6 and a < b) or (f3 == 7 and a >= b)
            if take:
                npc = (pc + imm) & 0xFFFFFFFF
        elif op == 0x03:                                # loads
            imm = _sx(ins >> 20, 12)
            addr = (x[rs1] + imm) & 0xFFFFFFFF
            sz = {0: 1, 1: 2, 2: 4, 4: 1, 5: 2}[f3]
            x[rd] = self._load(addr, sz, f3 in (0, 1, 2))
        elif op == 0x23:                                # stores
            imm = _sx(((ins >> 25) << 5) | ((ins >> 7) & 0x1F), 12)
            addr = (x[rs1] + imm) & 0xFFFFFFFF
            self._store(addr, {0: 1, 1: 2, 2: 4}[f3], x[rs2])
        elif op in (0x13, 0x33):                        # OP-IMM / OP
            if op == 0x13:
                b = _sx(ins >> 20, 12) & 0xFFFFFFFF
                shamt = (ins >> 20) & 0x1F
            else:
                b = x[rs2]
                shamt = b & 0x1F
            a = x[rs1]
            sa = _sx(a, 32)
            if f3 == 0:
                r = (a - b) & 0xFFFFFFFF if (op == 0x33 and f7 == 0x20) else (a + b) & 0xFFFFFFFF
            elif f3 == 1:
                r = (a << shamt) & 0xFFFFFFFF
            elif f3 == 2:
                r = 1 if sa < _sx(b, 32) else 0
            elif f3 == 3:
                r = 1 if a < b else 0
            elif f3 == 4:
                r = a ^ b
            elif f3 == 5:
                r = (sa >> shamt) & 0xFFFFFFFF if f7 == 0x20 else a >> shamt
            elif f3 == 6:
                r = a | b
            else:
                r = a & b
            x[rd] = r
        elif op == 0x0F:                                # FENCE -> nop
            pass
        elif op == 0x73:                                # SYSTEM (ECALL/EBREAK/CSR)
            if f3 == 0:                                 # ECALL/EBREAK -> stop
                self.halted = True
            else:                                       # CSR* -> rd = 0 (unused)
                x[rd] = 0
        # unknown ops fall through as nop

        x[0] = 0
        self.pc = npc
        self.icount += 1

    def run(self, max_steps, uart_poll_every=64):
        """Run up to max_steps instructions, decoding the bit-banged UART as we
        go. Returns instructions executed."""
        n = 0
        while n < max_steps and not self.halted:
            self.step()
            n += 1
            if (n & (uart_poll_every - 1)) == 0:
                self.uart.poll(self.icount)
        self.uart.poll(self.icount)
        return n
