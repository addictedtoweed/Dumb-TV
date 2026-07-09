/* dumbtv.h -- firmware SDK for the on-board SERV RISC-V core in Dumb-TV.
 *
 * The core drives the TV over the SAME framed serial protocol a host uses
 * (see docs/uart-protocol.md): it bit-bangs command frames out its one GPIO
 * pin, which the FPGA feeds back into the command parser as an internal source.
 * So firmware "talks to the TV" exactly like a host would -- input select, OSD,
 * backlight, picture controls, etc.
 *
 * Write your program as a single C file with a main(); include this header and
 * call the dumbtv_* helpers. The rest of the fw/ directory (start.S, dumbtv.ld,
 * build.sh) is one-time boilerplate you don't need to touch.
 *
 *     #include "dumbtv.h"
 *     int main(void) {
 *         dumbtv_uart_init();
 *         dumbtv_input_select(1);     // switch to input 1
 *         for (;;) { }
 *     }
 *
 * SPDX-License-Identifier: CC0-1.0  (public domain -- hack freely)
 */
#ifndef DUMBTV_H
#define DUMBTV_H

/* ---- SoC memory map (Servant) -----------------------------------------
 * RAM   @ 0x00000000  (this program)
 * GPIO  @ 0x40000000  (bit 0 = the serial-out line the FPGA listens on)
 * TIMER @ 0x80000000
 */
#define DUMBTV_GPIO (*(volatile unsigned int *)0x40000000u)

/* The GPIO is bidirectional: WRITING bit 0 drives the serial-out line (the
 * software UART below); READING bit 0 returns the consumer-IR receiver input
 * (idle high, active low -- e.g. a TSOP38238 demodulator). So the same address
 * is "UART out" on write and "IR in" on read. */
static inline unsigned int dumbtv_ir_read(void)   /* 1 = idle, 0 = carrier/mark */
{ return DUMBTV_GPIO & 1u; }

/* ---- bit-bang UART timing ----------------------------------------------
 * Each UART bit is held for DUMBTV_BIT_LOOPS iterations of a calibrated busy
 * loop. This MUST make the bit period match the FPGA receiver's CLKS_PER_BIT
 * for the internal link. SERV is bit-serial (slow), so a handful of loops
 * already spans many clocks -- tune this to your build's internal baud. The
 * default is calibrated for the simulation demo (INT_CLKS_PER_BIT in top_serv).
 */
#ifndef DUMBTV_BIT_LOOPS
#define DUMBTV_BIT_LOOPS 24u
#endif

/* opcodes (mirror rtl/cmd_parser.v and host/dumbtv.py) */
#define DUMBTV_OP_PING     0x01
#define DUMBTV_OP_INFO     0x02
#define DUMBTV_OP_EN       0x10
#define DUMBTV_OP_ALPHA    0x12
#define DUMBTV_OP_FBW      0x20
#define DUMBTV_OP_FBF      0x21
#define DUMBTV_OP_GUP      0x22
#define DUMBTV_OP_GBLIT    0x23
#define DUMBTV_OP_TEXT     0x24
#define DUMBTV_OP_FRECT    0x25
#define DUMBTV_OP_PAL      0x26
#define DUMBTV_OP_CLEAR    0x27
#define DUMBTV_OP_FLIP     0x28
#define DUMBTV_OP_BRIGHT   0x30
#define DUMBTV_OP_CONTR    0x31
#define DUMBTV_OP_BL       0x32
#define DUMBTV_OP_MUXSEL   0x40

#define DUMBTV_SYNC        0xA5

/* ---- low-level: bit-bang the software UART -----------------------------*/
static inline void dumbtv_delay(unsigned int n)
{
    volatile unsigned int i;
    for (i = 0; i < n; i++)
        __asm__ volatile("");      /* keep the loop; don't optimize away */
}

static inline void dumbtv_putbit(int level)
{
    DUMBTV_GPIO = (unsigned int)(level & 1);
    dumbtv_delay(DUMBTV_BIT_LOOPS);
}

static inline void dumbtv_putbyte(unsigned char v)
{
    int i;
    dumbtv_putbit(0);                          /* start bit */
    for (i = 0; i < 8; i++) {                  /* 8 data bits, LSB first */
        dumbtv_putbit(v & 1);
        v = (unsigned char)(v >> 1);
    }
    dumbtv_putbit(1);                          /* stop bit */
}

/* Raise the line to idle (mark) and settle before the first frame. */
static inline void dumbtv_uart_init(void)
{
    DUMBTV_GPIO = 1u;
    dumbtv_delay(DUMBTV_BIT_LOOPS * 8u);
}

/* ---- CRC-8/SMBUS (poly 0x07, init 0x00), matching the host -------------*/
static inline unsigned char dumbtv_crc8_step(unsigned char c, unsigned char b)
{
    int i;
    c ^= b;
    for (i = 0; i < 8; i++)
        c = (c & 0x80) ? (unsigned char)((c << 1) ^ 0x07)
                       : (unsigned char)(c << 1);
    return c;
}

/* ---- send one framed command: A5 | cmd | len16 | payload | crc8 --------*/
static inline void dumbtv_send_frame(unsigned char cmd,
                                     const unsigned char *payload,
                                     unsigned int len)
{
    unsigned char lo = (unsigned char)(len & 0xFF);
    unsigned char hi = (unsigned char)((len >> 8) & 0xFF);
    unsigned char crc = 0;
    unsigned int i;

    crc = dumbtv_crc8_step(crc, cmd);          /* CRC covers the body (no SYNC) */
    crc = dumbtv_crc8_step(crc, lo);
    crc = dumbtv_crc8_step(crc, hi);
    for (i = 0; i < len; i++)
        crc = dumbtv_crc8_step(crc, payload[i]);

    dumbtv_putbyte(DUMBTV_SYNC);
    dumbtv_putbyte(cmd);
    dumbtv_putbyte(lo);
    dumbtv_putbyte(hi);
    for (i = 0; i < len; i++)
        dumbtv_putbyte(payload[i]);
    dumbtv_putbyte(crc);
}

/* ---- high-level command wrappers (fire-and-forget; the core can't RX) ---*/
static inline void dumbtv_input_select(unsigned char sel)
{ unsigned char p = sel; dumbtv_send_frame(DUMBTV_OP_MUXSEL, &p, 1); }

static inline void dumbtv_enable(int on)
{ unsigned char p = on ? 1 : 0; dumbtv_send_frame(DUMBTV_OP_EN, &p, 1); }

static inline void dumbtv_alpha(unsigned char a)
{ dumbtv_send_frame(DUMBTV_OP_ALPHA, &a, 1); }

static inline void dumbtv_brightness(unsigned char level)   /* 128 = neutral */
{ dumbtv_send_frame(DUMBTV_OP_BRIGHT, &level, 1); }

static inline void dumbtv_contrast(unsigned char level)     /* 128 = unity */
{ dumbtv_send_frame(DUMBTV_OP_CONTR, &level, 1); }

static inline void dumbtv_backlight(unsigned char duty)     /* 0..255 PWM */
{ dumbtv_send_frame(DUMBTV_OP_BL, &duty, 1); }

static inline void dumbtv_clear(unsigned char index)
{ dumbtv_send_frame(DUMBTV_OP_CLEAR, &index, 1); }

static inline void dumbtv_flip(void)
{ dumbtv_send_frame(DUMBTV_OP_FLIP, 0, 0); }

static inline void dumbtv_ping(void)
{ dumbtv_send_frame(DUMBTV_OP_PING, 0, 0); }

#endif /* DUMBTV_H */
