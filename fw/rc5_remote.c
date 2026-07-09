/* rc5_remote.c -- RC5 (Philips) IR decoder + learn/match for the SERV core.
 *
 * RC5 is Manchester/bi-phase encoded: 14 bits, each a half-bit-time T of one
 * level then T of the other. A '1' is low-then-high (rising edge mid-bit), a '0'
 * is high-then-low; the line idles high and every frame opens with a '1' start
 * bit (so it begins with a falling edge). Bit period 2T.
 *
 * Decode by EDGE INTERVALS (robust, re-syncs on every edge -- no accumulated
 * timing drift): measure the first low (= one half-bit T, self-calibration),
 * then measure each successive same-level run and classify it short (1 half-bit)
 * or long (2 half-bits) against a 1.5T threshold, rebuilding the 28-half-bit
 * sequence. RC5's last half-bit is high when the frame ends in a '1', which
 * merges with the idle line -- so a 27th-of-28 run is padded high. Finally pair
 * the half-bits: [low,high] = 1, [high,low] = 0.
 *
 * Learn/match: store the first code, fire input_select(2) when it repeats,
 * input_select(1) otherwise.
 *
 * Build:   ./build.sh rc5_remote.c rc5_remote
 *
 * SPDX-License-Identifier: CC0-1.0
 */
#include "dumbtv.h"

#define RC5_HALF 28u            /* 14 bits * 2 half-bits */
#define RC5_INIT_CAP 4096u      /* first-low cap (that run is a half-bit, never idle) */

/* Count sample-loop iterations while the line stays at `level`, up to `cap`.
 * Returning `cap` means "at least this long" -- used to detect the idle gap
 * (a run far longer than a 2T bit) so the frame terminates promptly. */
static unsigned rc5_meas(unsigned level, unsigned cap)
{
    unsigned n = 0;
    while ((DUMBTV_GPIO & 1u) == level)
        if (++n >= cap)
            return cap;
    return n;
}

int main(void)
{
    unsigned learned_code = 0, learned = 0;

    dumbtv_uart_init();

    for (;;) {
        unsigned char hb[RC5_HALF];
        unsigned hn = 0, T, thr, idle, level, code, i;

        while ((DUMBTV_GPIO & 1u) == 0u) { }   /* ensure idle high */
        while ((DUMBTV_GPIO & 1u) == 1u) { }   /* wait for the start falling edge */

        T = rc5_meas(0, RC5_INIT_CAP);         /* first low = one half-bit */
        if (T < 2u || T >= RC5_INIT_CAP)
            continue;
        thr  = T + (T >> 1);                   /* 1.5T: short (1) vs long (2) run */
        idle = T << 2;                         /* 4T: anything longer is the idle gap */
        hb[hn++] = 0;                          /* first half-bit is low */
        level = 1u;                            /* next run is high */

        while (hn < RC5_HALF) {
            unsigned d = rc5_meas(level, idle);
            if (d >= idle)
                break;                         /* idle -> frame ended */
            hb[hn++] = (unsigned char)level;
            if (d > thr && hn < RC5_HALF)
                hb[hn++] = (unsigned char)level;
            level ^= 1u;
        }
        if (hn == RC5_HALF - 1u)               /* final '1' half-bit merged w/ idle */
            hb[hn++] = 1u;
        if (hn != RC5_HALF)
            continue;                          /* incomplete frame */

        code = 0;
        for (i = 0; i + 1u < RC5_HALF; i += 2u) {
            unsigned bit = (hb[i] == 0u && hb[i + 1u] == 1u) ? 1u : 0u;
            code = (code << 1) | bit;          /* MSB first */
        }

        if (!learned) {
            learned_code = code;
            learned = 1;
        } else if (code == learned_code) {
            dumbtv_input_select(2);
        } else {
            dumbtv_input_select(1);
        }
    }
    return 0;
}
