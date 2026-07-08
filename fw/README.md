# Dumb-TV firmware SDK (on-board SERV RISC-V core)

The TV has a tiny [SERV](https://github.com/olofk/serv) RV32I core on the FPGA
for on-board brains — IR remote learning, macros, custom control. Its firmware
is **uploaded over the serial port** (no flashing, no JTAG) into a 16 KB program
RAM, and it drives the display over the **same framed command protocol** a host
uses ([`docs/uart-protocol.md`](../docs/uart-protocol.md)) by bit-banging frames
out its GPIO pin, which the FPGA feeds back into the command parser as an
internal source.

It's fully hackable: write a C file, build it, upload it.

## You only write one C file

Everything else here is one-time boilerplate you don't touch:

| file | what it is |
|------|-----------|
| `dumbtv.h`  | the SDK — command API + software-UART + CRC (include this) |
| `example.c` | a starting-point `main()` — copy it |
| `start.S`   | crt0 (sets stack, zeroes bss, calls main) |
| `dumbtv.ld` | linker script (16 KB RAM at address 0) |
| `build.sh`  | one command: source → `.elf` + `.bin` |

## Build

Install a bare-metal RISC-V toolchain once:

```sh
sudo apt install gcc-riscv64-unknown-elf     # Debian/Ubuntu
```

Then:

```sh
./build.sh                    # example.c  -> firmware.bin
./build.sh myremote.c fw      # myremote.c -> fw.bin
```

## Upload

The `.bin` is loaded over the serial link (held in reset, written, released):

```python
from host.dumbtv import DumbTV
tv = DumbTV("/dev/serial0", 115200)
tv.load_firmware(open("fw/firmware.bin", "rb").read())   # halt -> write -> start
```

## Writing firmware

```c
#include "dumbtv.h"

int main(void) {
    dumbtv_uart_init();          // raise the line to idle
    dumbtv_input_select(1);      // same commands a host can send
    dumbtv_backlight(200);
    for (;;) { /* poll IR, react */ }
}
```

Available calls: `dumbtv_input_select`, `dumbtv_enable`, `dumbtv_alpha`,
`dumbtv_brightness`, `dumbtv_contrast`, `dumbtv_backlight`, `dumbtv_clear`,
`dumbtv_flip`, `dumbtv_ping`, plus `dumbtv_send_frame()` for any opcode. The core
is transmit-only (Servant's GPIO is output-only), so commands are fire-and-forget
— it doesn't read ACKs.

## Timing (important on real hardware)

The software UART bit period is `DUMBTV_BIT_LOOPS` busy-loop iterations. This must
make each bit last the FPGA receiver's `CLKS_PER_BIT` for the internal link
(`INT_CLKS_PER_BIT` in `rtl/top_serv.v`). SERV is bit-serial, so a few loops
already span many clocks. Override for your clock/baud:

```sh
CC="riscv64-unknown-elf-gcc -DDUMBTV_BIT_LOOPS=64" ./build.sh
```

The default is calibrated for the simulation demo.
