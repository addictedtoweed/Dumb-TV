"""dumbtv_sim.osd -- software twin of the FPGA OSD state (cmd_parser + canvas).

Applies protocol frames to an in-memory OSD: a double-buffered 4bpp indexed
canvas, a 16-entry ARGB palette, a glyph store, picture/backlight/mux config,
and the 16 KB firmware RAM. The semantics mirror rtl/cmd_parser.v exactly (byte
layouts, addressing, clipping, length checks, ACK/NACK), so the same command
stream drives this and the real hardware identically. It is NOT pixel-exact with
the RTL compositor -- that's compositor.py -- but faithful enough for firmware
and OSD-layout development.
"""

import numpy as np

from . import protocol as P


class OsdModel:
    def __init__(self, osd_w=160, osd_h=90, n_glyphs=256, gw=8, gh=12,
                 text_base=0, fw_size=16384):
        self.OSD_W, self.OSD_H = osd_w, osd_h
        self.N_GLYPHS, self.GW, self.GH = n_glyphs, gw, gh
        self.TEXT_BASE = text_base

        # double-buffered indexed canvas (front is displayed, writes hit back)
        self.bank = [np.zeros((osd_h, osd_w), np.uint8) for _ in range(2)]
        self.front = 0

        # 16-entry palette, ARGB; index 0 is transparent by convention
        self.palette = np.zeros((16, 4), np.uint8)     # columns: A, R, G, B

        # glyph store: N_GLYPHS x GH x GW of 4-bit indices (0 = transparent)
        self.glyphs = np.zeros((n_glyphs, gh, gw), np.uint8)

        # config registers (reset values match ctrl_regs.v)
        self.osd_enable = 0
        self.osd_alpha = 255
        self.brightness = 128
        self.contrast = 128
        self.backlight = 255
        self.mux_sel = 0
        self.core_halt = 1                              # held until FW_START
        self.lvds_cfg = 0x0001                          # native-LVDS mapping (24bpp/VESA)

        self.fw_ram = bytearray(fw_size)
        self.fw_dirty = False                          # set on FW_WRITE/START

    # ---- helpers -------------------------------------------------------------
    @property
    def back(self):
        return self.bank[self.front ^ 1]

    @property
    def shown(self):
        return self.bank[self.front]

    def _ack(self, cmd):
        return (P.RSP_ACK, bytes([cmd]))

    def _nack(self, cmd, err):
        return (P.RSP_NACK, bytes([cmd, err]))

    # ---- apply one frame -----------------------------------------------------
    def apply(self, cmd, payload):
        """Apply a (cmd, payload) frame; return (rsp_cmd, rsp_payload) like the
        FPGA (ACK / NACK / INFO)."""
        n = len(payload)
        fixed = {P.OP_EN: 1, P.OP_ALPHA: 1, P.OP_MUXSEL: 1, P.OP_BRIGHT: 1,
                 P.OP_CONTR: 1, P.OP_BL: 1, P.OP_FBF: 5, P.OP_PAL: 5,
                 P.OP_GBLIT: 5, P.OP_FRECT: 9, P.OP_GUP: 1 + self.GW * self.GH,
                 P.OP_LVDS: 2}
        zero = {P.OP_PING, P.OP_INFO, P.OP_FLIP, P.OP_FWHALT, P.OP_FWSTART}
        if cmd in fixed and n != fixed[cmd]:
            return self._nack(cmd, P.ERR_LEN)
        if cmd in zero and n != 0:
            return self._nack(cmd, P.ERR_LEN)
        if cmd == P.OP_CLEAR and n > 1:
            return self._nack(cmd, P.ERR_LEN)
        if cmd in (P.OP_FBW,) and n < 3:
            return self._nack(cmd, P.ERR_LEN)
        if cmd == P.OP_FW and n < 3:
            return self._nack(cmd, P.ERR_LEN)
        if cmd == P.OP_TEXT and n < 5:
            return self._nack(cmd, P.ERR_LEN)

        h = getattr(self, "_op_%02x" % cmd, None)
        if h is None:
            return self._nack(cmd, P.ERR_UNK)
        return h(payload)

    # ---- opcode handlers -----------------------------------------------------
    def _op_01(self, p):                                # PING
        return self._ack(P.OP_PING)

    def _op_02(self, p):                                # GET_INFO
        info = bytes([1, 0, 2]) + \
            self.OSD_W.to_bytes(2, "little") + self.OSD_H.to_bytes(2, "little") + \
            (1920).to_bytes(2, "little") + (1080).to_bytes(2, "little") + bytes([0])
        return (P.RSP_INFO, info)

    def _op_10(self, p):                                # OSD_ENABLE
        self.osd_enable = p[0] & 1
        return self._ack(P.OP_EN)

    def _op_12(self, p):                                # OSD_ALPHA
        self.osd_alpha = p[0]
        return self._ack(P.OP_ALPHA)

    def _op_20(self, p):                                # OSD_FB_WRITE
        addr = p[0] | (p[1] << 8)
        rng = False
        flat = self.back.reshape(-1)
        for b in p[2:]:
            if addr < self.OSD_W * self.OSD_H:
                flat[addr] = b & 0x0F
            else:
                rng = True
            addr += 1
        return self._nack(P.OP_FBW, P.ERR_RANGE) if rng else self._ack(P.OP_FBW)

    def _op_21(self, p):                                # OSD_FB_FILL
        addr = p[0] | (p[1] << 8)
        cnt = p[2] | (p[3] << 8)
        idx = p[4] & 0x0F
        flat = self.back.reshape(-1)
        rng = False
        for _ in range(cnt):
            if addr < flat.size:
                flat[addr] = idx
            else:
                rng = True
            addr += 1
        return self._nack(P.OP_FBF, P.ERR_RANGE) if rng else self._ack(P.OP_FBF)

    def _op_26(self, p):                                # PALETTE_SET
        i = p[0] & 0x0F
        self.palette[i] = [p[1], p[2], p[3], p[4]]      # A, R, G, B
        return self._ack(P.OP_PAL)

    def _op_27(self, p):                                # CLEAR (whole back canvas)
        idx = (p[0] & 0x0F) if len(p) else 0
        self.back[:] = idx
        return self._ack(P.OP_CLEAR)

    def _op_28(self, p):                                # FLIP
        self.front ^= 1
        return self._ack(P.OP_FLIP)

    def _op_25(self, p):                                # FILL_RECT
        x = p[0] | (p[1] << 8); y = p[2] | (p[3] << 8)
        w = p[4] | (p[5] << 8); ht = p[6] | (p[7] << 8)
        idx = p[8] & 0x0F
        x1 = min(x + w, self.OSD_W); y1 = min(y + ht, self.OSD_H)
        if x < self.OSD_W and y < self.OSD_H and x1 > x and y1 > y:
            self.back[y:y1, x:x1] = idx
        return self._ack(P.OP_FRECT)

    def _op_22(self, p):                                # GLYPH_UPLOAD
        slot = p[0]
        if slot >= self.N_GLYPHS:
            return self._nack(P.OP_GUP, P.ERR_RANGE)
        pix = np.frombuffer(bytes(x & 0x0F for x in p[1:]), np.uint8)
        self.glyphs[slot] = pix.reshape(self.GH, self.GW)
        return self._ack(P.OP_GUP)

    def _blit_glyph(self, slot, x, y):
        if slot >= self.N_GLYPHS:
            return
        g = self.glyphs[slot]
        for gy in range(self.GH):
            yy = y + gy
            if yy >= self.OSD_H:
                break
            for gx in range(self.GW):
                xx = x + gx
                if xx >= self.OSD_W:
                    break
                v = g[gy, gx]
                if v != 0:                              # 0 = transparent
                    self.back[yy, xx] = v

    def _op_23(self, p):                                # GLYPH_BLIT
        slot = p[0]
        if slot >= self.N_GLYPHS:
            return self._nack(P.OP_GBLIT, P.ERR_RANGE)
        x = p[1] | (p[2] << 8); y = p[3] | (p[4] << 8)
        self._blit_glyph(slot, x, y)
        return self._ack(P.OP_GBLIT)

    def _op_24(self, p):                                # DRAW_TEXT
        x = p[0] | (p[1] << 8); y = p[2] | (p[3] << 8)
        for i, ch in enumerate(p[4:]):
            self._blit_glyph((self.TEXT_BASE + ch) % self.N_GLYPHS,
                             x + i * self.GW, y)
        return self._ack(P.OP_TEXT)

    def _op_40(self, p):                                # INPUT_SELECT (mux)
        self.mux_sel = p[0] & 0x0F
        return self._ack(P.OP_MUXSEL)

    def _op_30(self, p):                                # BRIGHTNESS
        self.brightness = p[0]
        return self._ack(P.OP_BRIGHT)

    def _op_31(self, p):                                # CONTRAST
        self.contrast = p[0]
        return self._ack(P.OP_CONTR)

    def _op_32(self, p):                                # BACKLIGHT
        self.backlight = p[0]
        return self._ack(P.OP_BL)

    def _op_60(self, p):                                # LVDS output mapping
        self.lvds_cfg = p[0] | (p[1] << 8)              # invisible in preview
        return self._ack(P.OP_LVDS)

    def _op_50(self, p):                                # FW_HALT
        self.core_halt = 1
        return self._ack(P.OP_FWHALT)

    def _op_52(self, p):                                # FW_START
        self.core_halt = 0
        self.fw_dirty = True
        return self._ack(P.OP_FWSTART)

    def _op_51(self, p):                                # FW_WRITE
        addr = p[0] | (p[1] << 8)
        rng = False
        for b in p[2:]:
            if addr < len(self.fw_ram):
                self.fw_ram[addr] = b
            else:
                rng = True
            addr += 1
        self.fw_dirty = True
        return self._nack(P.OP_FW, P.ERR_RANGE) if rng else self._ack(P.OP_FW)
