"""Dumb-TV dev-kit sim -- interactive.

A window showing the composited output: one of 16 looped video streams
(vid_0..vid_15, or synthetic) with the OSD overlaid, driven through the real
command protocol. Control it live from the keyboard, and/or from a host script
over TCP (the serial path).

    python devkit/app.py [--videos DIR] [--port 5555] [--size 1280x720]

Keyboard:
    0-9            select input 0-9            LEFT/RIGHT  cycle all 16 inputs
    o              toggle OSD on/off           d           draw a demo OSD panel
    c              clear the OSD               [ / ]       brightness - / +
    ; / '          backlight  - / +            , / .       contrast   - / +
    ESC / q        quit

On-board core (--firmware fw/nec_remote.bin): the RISC-V emulator runs the real
firmware, whose bit-banged UART drives the OSD. IR keys synthesize remote codes
into its IR pin so you can test remote-learning live:
    z / x          send remote code A / B (NEC)      r           reset the core
Learn-then-match firmware: press z, z -> it learns then matches (input_select 2);
press z, x -> learns z, x doesn't match (input_select 1).

Serial path: connect a TCP client to localhost:5555 and send framed commands
(A5 | cmd | len16 | payload | crc8); responses come back the same way. See
host/dumbtv.py for the framing (point it at a socket, or reuse protocol.py).
"""

import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
import numpy as np                                                      # noqa: E402
from dumbtv_sim import OsdModel, Device, VideoBank, compositor          # noqa: E402
from dumbtv_sim import protocol as P                                    # noqa: E402
from dumbtv_sim.serialbridge import SerialBridge                        # noqa: E402


def demo_osd(send, osd):
    """Send a small demo overlay through the protocol (panel + bars)."""
    send(P.OP_PAL, bytes([1, 255, 255, 255, 255]))     # white
    send(P.OP_PAL, bytes([2, 150, 30, 40, 120]))       # translucent navy
    send(P.OP_PAL, bytes([3, 255, 250, 190, 40]))      # amber
    send(P.OP_PAL, bytes([4, 255, 40, 220, 180]))      # teal
    send(P.OP_EN, bytes([1]))
    send(P.OP_ALPHA, bytes([255]))
    send(P.OP_CLEAR, bytes([0]))
    W, H = osd.OSD_W, osd.OSD_H
    send(P.OP_FRECT, struct.pack("<HHHH", 6, 6, W - 12, H - 12) + bytes([2]))
    send(P.OP_FRECT, struct.pack("<HHHH", 6, 6, W - 12, 8) + bytes([3]))
    send(P.OP_FRECT, struct.pack("<HHHH", 6, 6, W - 12, 1) + bytes([1]))
    send(P.OP_FRECT, struct.pack("<HHHH", 6, H - 7, W - 12, 1) + bytes([1]))
    send(P.OP_FRECT, struct.pack("<HHHH", 12, H - 16, (W - 24) * 2 // 3, 3) + bytes([4]))
    send(P.OP_FLIP)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--videos", default=os.path.join(os.path.dirname(__file__), "videos"))
    ap.add_argument("--port", type=int, default=5555)
    ap.add_argument("--size", default="1280x720")
    ap.add_argument("--canvas", default="160x90")
    ap.add_argument("--firmware", default=None,
                    help="run a fw/*.bin on the on-board RISC-V emulator")
    ap.add_argument("--steps", type=int, default=40000,
                    help="emulator instructions per rendered frame")
    args = ap.parse_args()
    W, H = (int(v) for v in args.size.lower().split("x"))
    cw, ch = (int(v) for v in args.canvas.lower().split("x"))

    import pygame
    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("Dumb-TV dev-kit sim")
    font = pygame.font.SysFont("monospace", 16)
    clock = pygame.time.Clock()

    from dumbtv_sim import font
    osd = OsdModel(osd_w=cw, osd_h=ch, gw=font.GW, gh=font.GH)
    dev = Device(osd)
    bank = VideoBank(directory=args.videos, size=(W, H))
    bridge = SerialBridge(port=args.port)

    def send(cmd, payload=b""):
        dev.feed(P.build_frame(cmd, payload))

    # palette + font for OSD text (index 1 = white text, 2 = translucent panel)
    send(P.OP_PAL, bytes([1, 255, 240, 240, 240]))
    send(P.OP_PAL, bytes([2, 170, 20, 25, 40]))
    font.upload(send)

    banner_hide = [0]                                   # tick to auto-hide at

    def show_input_banner():
        text = f"INPUT {osd.mux_sel}".encode("latin-1")
        w = len(text) * font.GW + 6
        send(P.OP_EN, bytes([1]))
        send(P.OP_CLEAR, bytes([0]))
        send(P.OP_FRECT, struct.pack("<HHHH", 4, ch - 14, w, 12) + bytes([2]))
        send(P.OP_TEXT, struct.pack("<HH", 7, ch - 12) + text)
        send(P.OP_FLIP)
        banner_hide[0] = tick + 45                      # ~1.5 s at 30 fps

    # optional on-board RISC-V core running real firmware
    cpu = ir = None

    # virtual remote: keyboard -> distinct NEC codes (used when a firmware is
    # loaded, so the keyboard is the remote the firmware decodes/learns).
    REMOTE = {
        pygame.K_p: ("POWER", 0x10000001), pygame.K_i: ("INPUT", 0x10000002),
        pygame.K_m: ("MENU", 0x10000003), pygame.K_RETURN: ("OK", 0x10000004),
        pygame.K_UP: ("UP", 0x10000005), pygame.K_DOWN: ("DOWN", 0x10000006),
        pygame.K_LEFT: ("LEFT", 0x10000007), pygame.K_RIGHT: ("RIGHT", 0x10000008),
        pygame.K_EQUALS: ("VOL+", 0x10000009), pygame.K_MINUS: ("VOL-", 0x1000000A),
        pygame.K_PAGEUP: ("CH+", 0x1000000B), pygame.K_PAGEDOWN: ("CH-", 0x1000000C),
    }
    for n in range(10):                                  # digit buttons 0-9
        REMOTE[getattr(pygame, f"K_{n}")] = (f"{n}", 0x10000010 + n)

    def resolve_fw(path):
        # accept an absolute/relative path, or a bare name found in a bundled
        # fw/ (frozen build) or the repo's ../fw during source runs.
        here = getattr(sys, "_MEIPASS", os.path.dirname(__file__))
        for cand in (path, os.path.join(here, "fw", os.path.basename(path)),
                     os.path.join(os.path.dirname(__file__), "..", "fw",
                                  os.path.basename(path))):
            if os.path.exists(cand):
                return cand
        return path

    def load_firmware(path):
        from dumbtv_sim.riscv import RV32
        from dumbtv_sim.ir import IrSource
        nonlocal cpu, ir
        ir = IrSource()
        cpu = RV32(dev, ir_source=ir)
        with open(resolve_fw(path), "rb") as f:
            cpu.load(f.read())
        print(f"loaded firmware {path} on the RISC-V emulator")

    if args.firmware:
        load_firmware(args.firmware)

    print(f"listening for host commands on tcp://127.0.0.1:{args.port}")
    print(f"video decoding: {'opencv' if bank.have_cv2 else 'synthetic (no opencv)'}")
    if cpu is not None:
        keys = "  ".join(f"{pygame.key.name(k)}={n}" for k, (n, _) in REMOTE.items())
        print("virtual remote (keyboard -> IR):\n  " + keys + "\n  ` = reset core")
    else:
        print("keyboard: 0-9/arrows = input, o = OSD, d = demo, c = clear")
    print("panel: [ ] brightness   ; ' backlight   , . contrast   ESC quit")

    tick = 0
    running = True
    while running:
        # --- serial path: apply host commands, return responses ---
        data = bridge.poll()
        if data:
            bridge.send(dev.feed(data))

        # --- keyboard ---
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.KEYDOWN:
                k = e.key
                # meta + panel controls (always available)
                if k == pygame.K_ESCAPE:
                    running = False
                elif k == pygame.K_BACKQUOTE and args.firmware:
                    load_firmware(args.firmware)                    # reset core
                elif k == pygame.K_LEFTBRACKET:
                    send(P.OP_BRIGHT, bytes([max(0, osd.brightness - 8)]))
                elif k == pygame.K_RIGHTBRACKET:
                    send(P.OP_BRIGHT, bytes([min(255, osd.brightness + 8)]))
                elif k == pygame.K_SEMICOLON:
                    send(P.OP_BL, bytes([max(0, osd.backlight - 16)]))
                elif k == pygame.K_QUOTE:
                    send(P.OP_BL, bytes([min(255, osd.backlight + 16)]))
                elif k == pygame.K_COMMA:
                    send(P.OP_CONTR, bytes([max(0, osd.contrast - 8)]))
                elif k == pygame.K_PERIOD:
                    send(P.OP_CONTR, bytes([min(255, osd.contrast + 8)]))
                elif cpu is not None:
                    # firmware loaded: the keyboard is the IR remote
                    if k in REMOTE:
                        ir.send_nec(REMOTE[k][1], cpu.icount)
                else:
                    # no firmware: drive the OSD / mux directly
                    if pygame.K_0 <= k <= pygame.K_9:
                        send(P.OP_MUXSEL, bytes([k - pygame.K_0]))
                        show_input_banner()
                    elif k == pygame.K_RIGHT:
                        send(P.OP_MUXSEL, bytes([(osd.mux_sel + 1) & 15]))
                        show_input_banner()
                    elif k == pygame.K_LEFT:
                        send(P.OP_MUXSEL, bytes([(osd.mux_sel - 1) & 15]))
                        show_input_banner()
                    elif k == pygame.K_o:
                        send(P.OP_EN, bytes([0 if osd.osd_enable else 1]))
                    elif k == pygame.K_d:
                        demo_osd(send, osd)
                    elif k == pygame.K_c:
                        send(P.OP_CLEAR, bytes([0])); send(P.OP_FLIP)

        # --- auto-hide the input banner after its timeout ---
        if banner_hide[0] and tick >= banner_hide[0]:
            send(P.OP_CLEAR, bytes([0])); send(P.OP_FLIP)
            banner_hide[0] = 0

        # --- on-board core: run firmware; its UART drives dev/osd ---
        if cpu is not None:
            cpu.run(args.steps)

        # --- render: video -> composite -> window ---
        video = bank.frame(osd.mux_sel, tick)
        out = compositor.compose(video, osd)
        # numpy HxWx3 -> pygame surface (WxH)
        surf = pygame.surfarray.make_surface(np.transpose(out, (1, 0, 2)))
        screen.blit(surf, (0, 0))

        core = "" if cpu is None else f"  core {'run' if not osd.core_halt else 'halt'}"
        hud = (f"input {osd.mux_sel:2d} [{bank.sources[osd.mux_sel]}]  "
               f"osd {'on' if osd.osd_enable else 'off'}  "
               f"bright {osd.brightness} contr {osd.contrast} bl {osd.backlight}{core}")
        screen.blit(font.render(hud, True, (255, 255, 0), (0, 0, 0)), (6, H - 22))
        pygame.display.flip()
        tick += 1
        clock.tick(30)

    bridge.close()
    pygame.quit()


if __name__ == "__main__":
    main()
