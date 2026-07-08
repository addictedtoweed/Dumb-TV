# Vendored SERV RISC-V core

These files are **vendored, unmodified**, from the SERV project by Olof Kindgren:

- Upstream: <https://github.com/olofk/serv>
- License: **ISC** (see `LICENSE`) — redistributable with attribution.

SERV is the award-winning bit-serial RV32I core (~200 LUTs). Included here:

- `serv_*.v` — the core (`serv_rf_top.v` is the top: core + SRAM register file).
- `servant.v`, `servant_ram.v`, `servant_mux.v`, `servant_timer.v`,
  `servant_gpio.v` — the generic Servant SoC (SERV + Wishbone RAM + timer + a
  1-bit GPIO `q`, which firmware bit-bangs as a UART TX). Board-specific Servant
  wrappers are *not* vendored.

## How Dumb-TV integrates it (in progress)

The plan (see repo README roadmap, SERV step 3+):

1. Make the program RAM **host-writable** — adapt `servant_ram` (or a wrapper over
   the step-2 `fw_mem`) so `FW_WRITE` loads firmware while the core is halted.
2. Instantiate `serv_rf_top` gated by `core_rst` (from `FW_HALT`/`FW_START`).
3. Route the core's GPIO `q` (firmware bit-bangs commands on it) into an
   internal `uart_rx` → **source 1** of `cmd_mux`, so SERV drives the same OSD
   protocol as the host, arbitrated together.
4. IR receiver on a GPIO input; example firmware built with `riscv32-gcc`.

Not yet added to the Makefile build — integration lands incrementally so the
existing suites stay green.
