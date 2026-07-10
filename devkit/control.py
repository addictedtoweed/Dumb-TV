"""control.py -- drive the running sim over its virtual serial link (TCP).

Bypasses the keyboard: connect to the app's control port and send the exact same
framed commands a host MCU would over a real UART. Use it scripted or
interactively.

    python devkit/control.py --demo            # run a scripted OSD/mux demo
    python devkit/control.py input 5           # one command and exit
    python devkit/control.py                    # interactive: type commands

Interactive/one-shot commands:
    input N        select input 0-15        osd on|off      enable the OSD
    bright N       brightness 0-255         contrast N      contrast 0-255
    backlight N    backlight 0-255          demo            draw a demo overlay
    clear          wipe the OSD             ping / info     query the device
    quit
"""

import argparse
import os
import socket
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
from dumbtv_sim import protocol as P                                    # noqa: E402


class Link:
    """The 'virtual serial port': a socket speaking the framed UART protocol."""

    def __init__(self, host="127.0.0.1", port=5555, timeout=1.0):
        self.s = socket.create_connection((host, port), timeout=timeout)
        self.s.settimeout(timeout)
        self.parser = P.FrameParser()

    def cmd(self, op, payload=b""):
        self.s.sendall(P.build_frame(op, payload))
        try:
            frames = self.parser.feed(self.s.recv(4096))
        except socket.timeout:
            return None
        return frames[0] if frames else None

    # convenience wrappers
    def input_select(self, n): return self.cmd(P.OP_MUXSEL, bytes([n & 15]))
    def enable(self, on):      return self.cmd(P.OP_EN, bytes([1 if on else 0]))
    def brightness(self, v):   return self.cmd(P.OP_BRIGHT, bytes([v & 255]))
    def contrast(self, v):     return self.cmd(P.OP_CONTR, bytes([v & 255]))
    def backlight(self, v):    return self.cmd(P.OP_BL, bytes([v & 255]))
    def palette(self, i, a, r, g, b): return self.cmd(P.OP_PAL, bytes([i, a, r, g, b]))
    def fill_rect(self, x, y, w, h, idx):
        return self.cmd(P.OP_FRECT, struct.pack("<HHHH", x, y, w, h) + bytes([idx]))
    def clear(self, idx=0):    return self.cmd(P.OP_CLEAR, bytes([idx]))
    def flip(self):            return self.cmd(P.OP_FLIP)
    def ping(self):            return self.cmd(P.OP_PING)
    def info(self):            return self.cmd(P.OP_INFO)


def demo(link):
    link.palette(1, 255, 255, 255, 255)
    link.palette(2, 150, 30, 40, 120)
    link.palette(3, 255, 250, 190, 40)
    link.enable(1)
    link.clear(0)
    link.fill_rect(6, 6, 148, 78, 2)
    link.fill_rect(6, 6, 148, 8, 3)
    link.fill_rect(6, 6, 148, 1, 1)
    link.flip()
    print("drew demo overlay")


def do(link, args):
    c = args[0] if args else ""
    n = int(args[1]) if len(args) > 1 else 0
    if c == "input":       print(link.input_select(n))
    elif c == "osd":       print(link.enable(len(args) > 1 and args[1] == "on"))
    elif c == "bright":    print(link.brightness(n))
    elif c == "contrast":  print(link.contrast(n))
    elif c == "backlight": print(link.backlight(n))
    elif c == "clear":     link.clear(); link.flip()
    elif c == "demo":      demo(link)
    elif c == "ping":      print(link.ping())
    elif c == "info":      print(link.info())
    elif c in ("quit", "exit", "q"): return False
    elif c:                print(f"unknown: {c}")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5555)
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("cmd", nargs="*", help="a single command, e.g. input 5")
    a = ap.parse_args()
    link = Link(a.host, a.port)

    if a.demo:
        demo(link)
    elif a.cmd:
        do(link, a.cmd)
    else:
        print("connected. type commands (help: see control.py header); 'quit' to exit")
        try:
            while do(link, input("> ").split()):
                pass
        except (EOFError, KeyboardInterrupt):
            pass


if __name__ == "__main__":
    main()
