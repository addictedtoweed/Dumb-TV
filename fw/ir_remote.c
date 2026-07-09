/* ir_remote.c -- example IR remote decoder firmware for the on-board SERV core.
 *
 * Reads the consumer-IR receiver (GPIO bit 0, idle high / active low) and maps
 * a button press to a TV command. This example uses a deliberately simple,
 * protocol-agnostic scheme: it COUNTS the number of IR bursts (falling edges)
 * in a press, and selects that input (1 burst -> input 1, 2 -> input 2, ...).
 * A press ends after the line stays idle for DUMBTV_IR_GAP samples.
 *
 * It's a real, hackable starting point for IR control. Decoding an actual
 * protocol (NEC/RC5) or true "learning" builds on the same read loop by timing
 * the marks/spaces (dumbtv_ir_read + a cycle counter) instead of just counting
 * edges -- that's the next layer.
 *
 * Build:   ./build.sh ir_remote.c ir_remote
 *
 * SPDX-License-Identifier: CC0-1.0
 */
#include "dumbtv.h"

/* Consecutive idle (high) samples that mark the end of a press. Must exceed the
 * inter-burst gap (a few samples) but be reached during the long post-press
 * idle. Tune for your carrier/framing and sample rate. */
#ifndef DUMBTV_IR_GAP
#define DUMBTV_IR_GAP 16u
#endif

int main(void)
{
    dumbtv_uart_init();

    for (;;) {
        unsigned count = 0, highrun = 0, prev = 1;

        /* Accumulate one press: count high->low edges (bursts) until the line
         * has been idle long enough AND we actually saw activity. */
        for (;;) {
            unsigned line = dumbtv_ir_read();     /* 1 = idle, 0 = active */
            if (prev == 1u && line == 0u)
                count++;                           /* a burst began */
            if (line) {
                if (++highrun >= DUMBTV_IR_GAP && count)
                    break;                         /* press finished */
            } else {
                highrun = 0;
            }
            prev = line;
        }

        if (count >= 1u && count <= 8u)
            dumbtv_input_select((unsigned char)count);
    }
    return 0;
}
