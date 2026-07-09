# Dumb-TV dev kit (pure-Python sim)

A software **functional twin** of the Dumb-TV FPGA you can run on your desktop:
16 looped video streams through the input mux, the OSD overlaid, driven by the
**exact same command protocol** as the real hardware — over the keyboard, over a
host serial link, and (Phase B) from the on-board RISC-V core running the same
firmware binary. It's for fast, interactive OSD / firmware / IR-learning
development. The RTL under `rtl/` stays the hardware source of truth (the cocotb
suite is the accuracy reference); this is the quick, visible workbench.

It does **not** run at hardware speed or pixel-exactness — and doesn't try to.

## Install

```sh
pip install numpy pygame            # required for the app
pip install opencv-python           # optional: decode real videos (any codec)
```

## Run

```sh
python devkit/app.py                        # synthetic streams
python devkit/app.py --videos ~/clips       # your vid_0..vid_15
python devkit/app.py --size 1920x1080
```

Keyboard:

| key | action | key | action |
|-----|--------|-----|--------|
| `0`-`9` | select input 0-9 | `←` / `→` | cycle all 16 inputs |
| `o` | OSD on/off | `d` | draw a demo OSD panel |
| `c` | clear OSD | `[` / `]` | brightness − / + |
| `;` / `'` | backlight − / + | `,` / `.` | contrast − / + |
| `ESC` / `q` | quit | | |

## Video streams

Drop `vid_0` .. `vid_15` (any common container — `.mp4 .mkv .mov .avi .webm`)
in the videos directory; they're decoded with OpenCV/ffmpeg and looped, **no
re-encoding**. Any missing stream falls back to a distinct animated synthetic
pattern (each shows *N+1* white blocks so you can tell the inputs apart), so the
sim runs with zero files.

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
| `dumbtv_sim/riscv.py` | **(Phase B)** RV32I emulator: run the on-board firmware, IR learning from the keyboard |

## Status

- **Phase A (done):** serial + keyboard control of the OSD over 16 muxed video
  streams; verified headless (`selftest.py`).
- **Phase B (next):** a pure-Python RV32I emulator runs the actual `fw/*.bin`;
  its bit-banged UART drives the OSD, and keyboard-synthesized NEC/RC5 frames on
  its IR pin exercise the remote-learning firmware — the "internal processor"
  path.
