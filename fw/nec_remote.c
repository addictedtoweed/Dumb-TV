/* nec_remote.c -- NEC-protocol IR decoder + simple remote-learning for the
 * on-board SERV core.
 *
 * Decodes the standard NEC IR frame off the receiver pin (GPIO bit 0, idle high
 * / active low):
 *
 *     leader  : ~9 ms mark  + ~4.5 ms space
 *     32 bits : each a ~562 us mark then a space -- short space = 0,
 *               long space (~1.7 ms) = 1  (LSB first)
 *
 * Rather than hard-code microsecond thresholds (which depend on the FPGA clock),
 * it MEASURES the leader mark and sets the bit-space threshold to leader/8 --
 * halfway between a '0' and a '1' space. That makes the decoder clock- and
 * scale-independent: it self-calibrates to whatever timing arrives.
 *
 * "Learning": the first code seen is stored; when that same code repeats, it
 * fires input_select(2); any other code fires input_select(1). Extend the table
 * for a full learn-N-buttons remote.
 *
 * Build:   ./build.sh nec_remote.c nec_remote
 *
 * SPDX-License-Identifier: CC0-1.0
 */
#include "dumbtv.h"

/* Safety cap so a stuck/noisy line can't spin a measure loop forever. Far above
 * any real mark/space in sample-loop iterations. */
#define NEC_CAP 0x40000u

/* Count sample-loop iterations while the IR line stays at `level` (0 or 1). */
static unsigned nec_measure(unsigned level)
{
    unsigned n = 0;
    while ((DUMBTV_GPIO & 1u) == level)
        if (++n >= NEC_CAP)
            break;
    return n;
}

int main(void)
{
    unsigned long learned_code = 0;
    unsigned learned = 0;

    dumbtv_uart_init();

    for (;;) {
        int i;
        unsigned long code = 0;
        unsigned L, thresh;

        /* resync to idle, then wait for the leader's falling edge */
        while ((DUMBTV_GPIO & 1u) == 0u) { }
        while ((DUMBTV_GPIO & 1u) == 1u) { }

        L = nec_measure(0);             /* leader mark (long) */
        (void)nec_measure(1);           /* leader space */
        thresh = L >> 3;                /* leader/8: between a '0' and '1' space */

        for (i = 0; i < 32; i++) {
            unsigned s;
            (void)nec_measure(0);       /* bit mark (ignored) */
            s = nec_measure(1);         /* bit space: long => 1 */
            code >>= 1;
            if (s > thresh)
                code |= 0x80000000ul;   /* LSB-first: first bit ends at bit 0 */
        }

        if (!learned) {                 /* learn the first code */
            learned_code = code;
            learned = 1;
        } else if (code == learned_code) {
            dumbtv_input_select(2);     /* known button */
        } else {
            dumbtv_input_select(1);     /* some other button */
        }
    }
    return 0;
}
