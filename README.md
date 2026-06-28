# dp-osd-fpga — simulation-first scaffold

A tiny, fully-testable Verilog pipeline for the "dumb TV" video path:

```
  video_timing + pattern_gen        osd_compositor              (output)
  ───────────────────────────►  ───────────────────────►  ───────────────►
   stand-in for DP RX            recover (x,y) from de,      to LVDS (1080p
   (gradient test pattern)       alpha-blend OSD over        prototype) or
                                 video, 1-clock latency      DP TX (product)
                                        ▲
                                   ctrl_regs  ◄── UART control plane
                                   (OSD pos/size/color/alpha, picture ctrl)
```

The point of this scaffold: **develop and regression-test the entire
compositor / OSD / control logic in Verilator with zero hardware**, then only
touch a board to validate the PHY/IP plumbing. Everything here is board- and
vendor-tool independent.

## What maps to what in the real product

| Scaffold block      | Real product                                              |
|---------------------|----------------------------------------------------------|
| `video_timing`+`pattern_gen` | DisplayPort RX IP (licensed) + transceivers     |
| `osd_compositor`    | unchanged — your value-add (overlay + low latency)       |
| `ctrl_regs`         | UART command parser fed by the Linux host's serial port  |
| top output stream   | LVDS out (1080p prototype) → DP TX → swappable panel adapter |

Low latency / "zero frame interpolation" is structural: we blend per-pixel as
the stream flows (one clock), never buffering a frame, so we never synthesize
new frames. Genlock the output clock to the recovered input clock on hardware
to keep added latency at one line, not one frame.

## Prerequisites

- Python 3.8+
- [cocotb](https://www.cocotb.org/)  `pip install cocotb`
- [Verilator](https://verilator.org/)  (`pacman -S mingw-w64-x86_64-verilator` under MSYS2, or `apt install verilator` under WSL)
- GTKWave (optional, for waveforms)

On Windows the smoothest path is **WSL** or **MSYS2** — cocotb+Verilator are
happiest in a Unix-y shell.

## Run

```sh
make            # runs test_passthrough and test_overlay
make WAVES=1    # also writes dump.vcd
make clean
```

Compositor tests (`TOPLEVEL=top`):
- `test_passthrough` — OSD off ⇒ output equals the input gradient exactly.
- `test_framebuffer_overlay` — OSD on ⇒ framebuffer texel blended inside the
  window (with master fade), untouched outside.

UART control-plane tests (run separately):

```sh
make TOPLEVEL=top_uart MODULE=test_uart
```

- `test_ping` / `test_get_info` — framing + ACK/INFO responses decode correctly.
- `test_bad_crc` — a corrupt frame returns NACK with the CRC error code.
- `test_overlay_upload` — the *full chain*: serial FILL→FB_WRITE→WINDOW/ALPHA/
  ENABLE actually puts the uploaded overlay on the video output, pixel-exact.

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
3. **Picture controls** — add BRIGHTNESS/CONTRAST registers + a pixel-math stage
   in the compositor (the protocol already reserves the opcodes).
4. **OSD upscaler** — render OSD at e.g. 720p and bilinear-upscale to active,
   so the framebuffer stays small but the overlay looks crisp at 1080p.
5. **Real I/O** — swap `pattern_gen` for the vendor DP RX IP and the output
   for LVDS, on the chosen prototype board.

See `docs/uart-protocol.md` for the host (Pi) serial protocol.
