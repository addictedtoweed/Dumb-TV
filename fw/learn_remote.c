/* learn_remote.c -- autonomous multi-button IR learn wizard for the SERV core.
 *
 * On boot the firmware walks a fixed list of TV actions and, for each, drives an
 * on-screen prompt and waits for the user to press a remote button -- binding
 * that button's NEC code to the action. After all actions are learned it runs
 * normally: decode each press, look it up in the table, and fire the mapped
 * command. This is fully self-contained -- no host needed -- so any universal
 * remote (HTPC-style, 100+ buttons) can be taught in one pass. The table is
 * sized for a big remote; the demo learns N_ACTIONS of them.
 *
 * The action here is input_select(action+1) so it's observable; a real build
 * would map each action to whatever command it drives.
 *
 * Build:   ./build.sh learn_remote.c learn_remote
 *
 * SPDX-License-Identifier: CC0-1.0
 */
#include "dumbtv.h"

#define NEC_CAP    0x40000u
#define MAX_LEARN  128u                 /* room for a big universal remote */
#ifndef N_ACTIONS
#define N_ACTIONS  4u                   /* buttons to learn in this build */
#endif

static unsigned long g_codes[MAX_LEARN];

static unsigned nec_measure(unsigned level)
{
    unsigned n = 0;
    while ((DUMBTV_GPIO & 1u) == level)
        if (++n >= NEC_CAP)
            break;
    return n;
}

/* Wait for and decode one NEC frame; returns the 32-bit code. */
static unsigned long nec_read(void)
{
    unsigned L, thr, i;
    unsigned long code = 0;

    while ((DUMBTV_GPIO & 1u) == 0u) { }
    while ((DUMBTV_GPIO & 1u) == 1u) { }
    L = nec_measure(0);                 /* leader mark */
    (void)nec_measure(1);               /* leader space */
    thr = L >> 3;
    for (i = 0; i < 32u; i++) {
        unsigned s;
        (void)nec_measure(0);           /* bit mark */
        s = nec_measure(1);             /* bit space: long => 1 */
        code >>= 1;
        if (s > thr)
            code |= 0x80000000ul;
    }
    return code;
}

/* Show which action is being learned: a bar whose width grows with the index. */
static void prompt(unsigned i)
{
    dumbtv_enable(1);
    dumbtv_clear(0);
    dumbtv_fill_rect(6, 6, 12, 8, 2);               /* marker box */
    dumbtv_fill_rect(24, 8, (i + 1) * 6, 4, 1);     /* progress bar = action i */
    dumbtv_flip();
}

int main(void)
{
    unsigned i;

    dumbtv_uart_init();
    dumbtv_palette(1, 255, 250, 200, 40);           /* amber */
    dumbtv_palette(2, 255, 240, 240, 240);          /* white */

    /* ---- learn phase: bind one remote button per action ---- */
    for (i = 0; i < N_ACTIONS; i++) {
        prompt(i);
        g_codes[i] = nec_read();
    }
    dumbtv_clear(0);                                 /* done: wipe the prompt */
    dumbtv_flip();

    /* ---- normal phase: decode presses and fire the mapped action ---- */
    for (;;) {
        unsigned long c = nec_read();
        for (i = 0; i < N_ACTIONS; i++) {
            if (c == g_codes[i]) {
                dumbtv_input_select((unsigned char)(i + 1));
                break;
            }
        }
    }
    return 0;
}
