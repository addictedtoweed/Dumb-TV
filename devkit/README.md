# Dumb-TV dev kit (pure-Python sim)

A software **functional twin** of the Dumb-TV FPGA you can run on your desktop:
16 looped video streams through the input mux, the OSD overlaid, driven by the
**exact same command protocol** as the real hardware — over the keyboard, over a
host serial link, and (Phase B) from the on-board RISC-V core running the same
firmware binary. It's for fast, interactive OSD / firmware / IR-learning
development. The RTL under `rtl/` stays the hardware source of truth (the cocotb
suite is the accuracy reference); this is the quick, visible workbench.

It does **not** run at hardware speed or pixel-exactness — and doesn't try to.

## Quick start (nothing installed globally)

The launcher makes a local `.venv` the first time, installs the deps into it, and
runs — nothing touches your system Python. Needs Python 3.9+.

```sh
./run.sh                                   # Linux / macOS / WSL
run.bat                                    # Windows
```

Or plain, if you already have the deps (`pip install numpy pygame opencv-python`):

```sh
python app.py [--size 1920x1080] [--videos videos] [--firmware ../fw/learn_remote.bin]
```

For a **truly zero-install** bundle (no Python at all) to hand out on a GitHub
Release, see *Packaging* below.

## Video streams

Drop up to 16 clips named `vid_0` .. `vid_15` (any container — `.mp4 .mkv .mov
.avi .webm .m4v .y4m`) into `videos/`. They're decoded with OpenCV/ffmpeg and
looped, **no re-encoding**. Any missing input falls back to a distinct animated
pattern (each shows *N+1* white blocks so you can tell the inputs apart), so it
runs with zero files.

## Two ways to control it

**1 — keyboard as a virtual remote.** Load a firmware and the keyboard becomes
the IR remote it decodes/learns:

```sh
./run.sh --firmware ../fw/learn_remote.bin      # autonomous 100+ button learn wizard
```

Keys map to distinct remote buttons (`p`=power, `i`=input, `m`=menu, arrows, enter
=OK, `=`/`-`=vol, PgUp/PgDn=ch, digits `0`-`9`); the legend prints at startup and
`` ` `` resets the core. With the learn wizard: follow the on-screen prompts,
press a key per action to bind it, then those keys drive the TV.

Without `--firmware`, the keyboard drives the OSD directly (dev mode): `0`-`9` /
arrows pick the input, `o` OSD on/off, `d` demo panel, `c` clear.

Panel tweaks always work: `[` `]` brightness, `;` `'` backlight, `,` `.` contrast.

**2 — a script over the virtual serial link.** The app listens on
`tcp://127.0.0.1:5555`; `control.py` speaks the exact framed UART protocol a host
MCU would, bypassing the keyboard:

```sh
python control.py --demo         # scripted OSD + mux demo
python control.py input 5        # one command
python control.py                # interactive: type  input 3 / bright 150 / osd on / demo
```

## Packaging a zero-install release

```sh
packaging/build.sh          # or packaging\build.bat on Windows
```

Runs PyInstaller (installing it into the venv) and produces `dist/dumbtv-devkit/`
— a self-contained folder with the app, the firmware images, and an empty
`videos/`. Zip that folder and attach it to a GitHub **Release**; anyone can
unzip, drop in videos, and run the executable with **no Python installed**.

Licensing: the dev-kit code is CC0 (public domain). Bundled builds also carry
numpy (BSD), pygame (LGPL), and — if you keep real-video decoding — FFmpeg via
opencv-python (LGPL); ship their licenses with a bundle. See `NOTICE`.

## Serial path (host control)

The app listens on `tcp://127.0.0.1:5555`. Send framed commands
(`A5 | cmd | len16 | payload | crc8`, CRC-8/SMBUS) and read the ACK/NACK/INFO
responses — byte-identical to the real UART. `dumbtv_sim/protocol.py` has the
framing (`build_frame`, opcodes); `host/dumbtv.py` uses the same wire format.

## Headless self-test

```sh
python devkit/selftest.py           # drives the OSD, writes devkit/out.png
```

## Layout

| module | role |
|--------|------|
| `dumbtv_sim/protocol.py` | framing, CRC, opcodes, incremental frame parser |
| `dumbtv_sim/osd.py` | software OSD twin (canvas, palette, glyphs, config) — mirrors `cmd_parser.v` |
| `dumbtv_sim/compositor.py` | picture controls + upscale + alpha blend + backlight — mirrors `osd_compositor.v` |
| `dumbtv_sim/video.py` | 16 looped streams (OpenCV) + synthetic fallback |
| `dumbtv_sim/device.py` | byte-stream → frames → OSD (both host and core feed this) |
| `dumbtv_sim/serialbridge.py` | TCP server for host control |
| `app.py` | interactive pygame front-end |
| `dumbtv_sim/riscv.py` | RV32I emulator: runs the on-board firmware; its bit-banged UART drives the OSD |
| `dumbtv_sim/ir.py` | synthesizes NEC/RC5 IR waveforms into the core's IR pin (keyboard remote) |

## On-board core (run real firmware)

```sh
python devkit/app.py --firmware fw/nec_remote.bin
```

The RISC-V emulator runs the same `.bin` the FPGA's SERV core would; its
bit-banged UART is decoded and drives the OSD. Press `z` / `x` to fire two
different NEC remote codes at its IR pin — with the learning firmware, `z z`
learns then matches (→ input 2), `z x` learns z then sees a new code (→ input 1).
`r` resets the core. Swap in `fw/rc5_remote.bin` for RC5.

Headless regression:

```sh
python devkit/test_emulator.py      # runs firmware.bin / nec / rc5 on the emulator
```

## Status

- **Phase A (done):** serial + keyboard control of the OSD over 16 muxed video
  streams; verified headless (`selftest.py`).
- **Phase B (done):** a pure-Python RV32I emulator runs the actual `fw/*.bin`;
  its bit-banged UART drives the OSD, and keyboard-synthesized NEC/RC5 frames on
  its IR pin exercise the remote-learning firmware — the "internal processor"
  path. Verified headless (`test_emulator.py`).
