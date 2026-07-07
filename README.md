# Dumb-TV — simulation-first OSD scaffold

A tiny, fully-testable Verilog pipeline for the "dumb TV" video path.

**Input is parallel RGB.** The FPGA does *not* receive HDMI/DVI/DP itself — an
off-the-shelf transceiver/bridge chip (e.g. Lontium LT-series or TI TFP401)
receives the high-speed standard and hands the FPGA a generic parallel video bus
(pixel clock + DE/HSync/VSync + 24-bit RGB). The proprietary standard, and any
license, stays sealed inside that chip; the published FPGA bitstream carries no
licensed IP, needs no fabric transceivers, and works on a cheap FPGA. Swap the
bridge to change input standard.

```
  bridge chip ─▶ rgb_in ─▶   osd_compositor    ─▶ parallel ─▶ RGB-to-LVDS ─▶ panel
  (HDMI/DVI/DP   sample    upscale canvas +        RGB out    serializer
   → parallel    the RGB   palette-blend OSD                  (off-the-shelf,
   RGB; off-     bus on    over video                          FPD-Link)
   the-shelf)    pclk            ▲
                          ctrl_regs ◄── UART control plane
                          (enable/alpha, glyph blits, palette, picture ctrl)
```

Both the high-speed input (HDMI/DVI/DP → RGB) and output (RGB → LVDS) are
handled by commodity bridge/serializer chips, so the FPGA is a pure
**parallel-RGB processor** — cheap, low pin-count, and carrying no licensed IP.

In simulation, `video_timing + pattern_gen` stands in for the bridge's parallel
output (a gradient test pattern) so the whole pipeline runs with zero hardware.

The point of this scaffold: **develop and regression-test the entire
compositor / OSD / control logic in Verilator with zero hardware**, then only
touch a board to validate the bridge + output plumbing. Everything here is
board- and vendor-tool independent.

## What maps to what in the real product

| Scaffold block      | Real product                                              |
|---------------------|----------------------------------------------------------|
| `rgb_in` / `video_timing`+`pattern_gen` | parallel-RGB bridge chip (Lontium LT-series / TI TFP401) that receives HDMI/DVI/DP and outputs pixel clock + DE/HS/VS + RGB — proprietary IP + any license sealed in the chip |
| `osd_compositor`    | unchanged — your value-add (overlay + low latency)       |
| `osd_fb`            | dual-clock BRAM: UART-clock write, pixel-clock read      |
| `cmd_parser`+`ctrl_regs` | UART command parser fed by the Linux host's serial port |
| top output stream   | parallel RGB out → off-the-shelf RGB-to-LVDS serializer (FPD-Link / FlatLink, e.g. TI SN75LVDS83B / Lontium) → panel |

**Canonical input = parallel RGB.** Rather than receive HDMI/DVI/DP in the FPGA
fabric (transceivers + licensed IP), a commodity bridge chip does that and hands
the FPGA a generic parallel video bus. Benefits: no high-speed serial logic, a
cheaper FPGA, and a **fully license-clean bitstream** (nothing proprietary in
the published RTL — ideal for open-source distribution). 1080p60 today; 4K later
needs DP or a multi-pixel bridge. `rgb_in` is just the pin-sampling stage; swap
the bridge to change input standard.

**Two clock domains.** The pixel clock arrives from the bridge; the control
plane runs on an independent system clock (`top_rgb`). The two crossings are the
dual-clock `osd_fb` (pixel data) and `sync2` on the quasi-static OSD config.
`top.v` / `top_uart.v` keep everything on one clock for simpler unit tests.

**Canvas storage — BRAM or external PSRAM (build-selectable).** The OSD canvas
is a swappable module behind a `(cx, cy, new_frame) -> index` read contract:

```
make            # CANVAS=bram  (default): canvas in on-chip block RAM
make CANVAS=psram   # canvas in external SDRAM/PSRAM (many cheap FPGAs bundle ~64 Mbit)
```

`osd_fb_bram.v` is a plain dual-port RAM. `osd_fb_psram.v` is the same interface
backed by external memory, with a BRAM line-buffer prefetch (the `cx/cy/new_frame`
port is what lets it hide the memory latency) — the sim uses a behavioral memory
model so the whole OSD verifies against the PSRAM build, and the header marks the
board memory-controller integration point. Both pass the full suite unchanged, so
open-source builds pick whichever their board favors.

Low latency / "zero frame interpolation" is structural: we blend per-pixel as
the stream flows (one clock), never buffering a frame, so we never synthesize
new frames. Genlock the output clock to the input clock on hardware to keep
added latency at one line, not one frame.

## Prerequisites

- Python 3.8+
- [cocotb](https://www.cocotb.org/)  `pip install cocotb`
- [Verilator](https://verilator.org/)  (`pacman -S mingw-w64-x86_64-verilator` under MSYS2, or `apt install verilator` under WSL)
- GTKWave (optional, for waveforms)

On Windows the smoothest path is **WSL** or **MSYS2** — cocotb+Verilator are
happiest in a Unix-y shell.

## Run

Under WSL, `./sim.sh` activates the cocotb venv and uses a space-free build dir
(see `SETUP.md`). Three suites:

```sh
./sim.sh                                       # compositor pipeline  (top)
./sim.sh TOPLEVEL=top_uart MODULE=test_uart    # UART control plane   (top_uart)
./sim.sh TOPLEVEL=top_rgb  MODULE=test_rgb     # two-clock RGB front-end (top_rgb)
```

(Or `make ...` directly if you manage the venv/build dir yourself. `WAVES=1`
also writes a VCD.)

- **Compositor** — `test_passthrough` (OSD off ⇒ output equals input) and
  `test_framebuffer_overlay` (framebuffer texel blended inside the window).
- **UART** — `test_ping`/`test_get_info` (framing + responses), `test_bad_crc`
  (corrupt frame ⇒ NACK), `test_overlay_upload` (serial FILL→FB_WRITE→
  WINDOW/ALPHA/ENABLE puts the uploaded overlay on the video output).
- **RGB (two-clock)** — same overlay upload but with UART on `sclk` and video on
  an asynchronous `pclk`, so the dual-clock framebuffer and the `sync2` config
  crossing are actually exercised.

All tests compare against a Python model of the *exact* gradient/blend/CRC math,
so any logic change that breaks a pixel or a byte fails the build.

## Scaling to 1080p

The timing is parameterized. For real 1080p60 timing, override
`video_timing`'s parameters (e.g. `H_ACTIVE=1920, H_FP=88, H_SYNC=44,
H_BP=148, V_ACTIVE=1080, V_FP=4, V_SYNC=5, V_BP=36`). Keep the tiny defaults
for fast cocotb iteration; only synthesize at full size.

## OSD framebuffer

The OSD is now a small block-RAM framebuffer (`osd_fb.v`), `OSD_W` x `OSD_H`
texels (powers of two), each packed `{alpha[31:24], R[23:16], G[15:8], B[7:0]}`.
The host loads it through the `fb_we / fb_waddr / fb_wdata` port (in sim, cocotb
does). The compositor reads the matching texel and blends:

```
  eff_alpha = fb_alpha * OSD_ALPHA / 256        (per-pixel * master fade)
  out       = vid*(256-eff)/256 + fb_rgb*eff/256
```

This makes the OSD fully customizable (text, menus, logos) — render the image
on the host, push it over the framebuffer port. Compositor latency is now two
clocks (pipelined around the 1-clock RAM read); still no frame buffering.

## Control register map (`ctrl_regs.v`)

| Addr | Name        | Notes                                  |
|------|-------------|----------------------------------------|
| 0    | OSD_ENABLE  | bit0                                   |
| 1    | OSD_X0      | window left (on-screen position)       |
| 2    | OSD_Y0      | window top                             |
| 3    | OSD_W       | window width  (<= framebuffer OSD_W)   |
| 4    | OSD_H       | window height (<= framebuffer OSD_H)   |
| 5    | OSD_ALPHA   | master fade, 0=off .. 255=full         |

OSD pixel color/alpha come from the framebuffer, not registers.

## Next steps (in rough order)

1. ~~**Framebuffer OSD**~~ — done (`osd_fb.v`).
2. ~~**UART front-end**~~ — done (`uart_rx.v`, `uart_tx.v`, `cmd_parser.v`,
   `top_uart.v`); implements `docs/uart-protocol.md`.
3. ~~**Parallel-RGB front-end + two clock domains**~~ — done (`rgb_in.v`,
   `sync2.v`, dual-clock `osd_fb.v`, `top_rgb.v`).
4. **Picture controls** — add BRIGHTNESS/CONTRAST registers + a pixel-math stage
   in the compositor (the protocol already reserves the opcodes).
5. **OSD upscaler** — render OSD at e.g. 720p and bilinear-upscale to active,
   so the framebuffer stays small but the overlay looks crisp at 1080p.
6. **Real I/O** — feed `rgb_in` from a real bridge chip (Lontium/TFP401) and
   drive the parallel-RGB output into an RGB-to-LVDS serializer, on the chosen
   prototype board. (No RTL change — the FPGA is parallel-RGB in and out.)

See `docs/uart-protocol.md` for the host (Pi) serial protocol.
