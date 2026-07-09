"""dumbtv_sim.ir -- synthesize IR receiver waveforms for the emulator's GPIO-in.

Drives the on-board core's IR pin (read at GPIO bit 0, idle high / active low) so
the remote-learning firmware can be exercised from the keyboard. Timing is in the
emulator's instruction count; the decoders self-calibrate, so absolute scale only
needs the protocol's ratios. Supports NEC and RC5 (the two decoders in fw/).
"""

import bisect


class IrSource:
    def __init__(self):
        self.pts_t = []            # sorted change-point times (icount)
        self.pts_l = []            # line level in effect from that time

    def level(self, t):
        if not self.pts_t:
            return 1               # idle high
        i = bisect.bisect_right(self.pts_t, t) - 1
        return self.pts_l[i] if i >= 0 else 1

    def _emit(self, segs, now):
        t = max(now, (self.pts_t[-1] + 1) if self.pts_t else now)
        for lv, dur in segs:
            self.pts_t.append(t)
            self.pts_l.append(lv)
            t += dur
        self.pts_t.append(t)
        self.pts_l.append(1)       # return to idle

    def send_nec(self, code32, now, U=40):
        """NEC: 16U/8U leader, 32 bits (1U mark + 1U/3U space, LSB first), stop."""
        segs = [(0, 16 * U), (1, 8 * U)]
        for i in range(32):
            bit = (code32 >> i) & 1
            segs.append((0, U))
            segs.append((1, (3 if bit else 1) * U))
        segs.append((0, U))
        self._emit(segs, now)

    def send_rc5(self, bits14, now, U=60):
        """RC5: 14 bits bi-phase, MSB first; '1' = low-then-high, '0' = high-then-low."""
        segs = []
        for k in range(14):
            bit = (bits14 >> (13 - k)) & 1
            segs += [(0, U), (1, U)] if bit else [(1, U), (0, U)]
        self._emit(segs, now)
