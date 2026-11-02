# WeAct Studio Display FS (3.5" e 0.96"). EXPERIMENTAL: escrito a partir da documentação
# pública do protocolo, sem teste em hardware. Ver docs/telas.md.
#
# Protocolo: cada comando termina com 0x0A; inteiros de 16 bits little-endian; SET_BITMAP
# (0x05) leva x0 y0 x1 y1 (cantos inclusivos) e logo depois os pixels RGB565 little-endian.
# A orientação é feita pelo firmware (2 = paisagem); as coordenadas passam a ser as da imagem girada.
import struct

import numpy as np
import serial

from byorzin_monitor.display.backends.base import Backend

END = 0x0A
SET_ORIENTATION, SET_BRIGHTNESS, FULL, SET_BITMAP, FREE, SYSTEM_VERSION = 0x02, 0x03, 0x04, 0x05, 0x07, 0x42
LANDSCAPE = 2
TILE = 16


def cmd(code, *fmt_args, fmt=""):
    return bytes([code]) + (struct.pack("<" + fmt, *fmt_args) if fmt else b"") + bytes([END])


def rgb565_le(arr):
    a = arr.astype(np.uint16)
    v = ((a[..., 0] & 0xF8) << 8) | ((a[..., 1] & 0xFC) << 3) | (a[..., 2] >> 3)
    return v.astype("<u2")


class WeAct(Backend):
    """WeAct Studio Display FS 3.5" — experimental, não testado em hardware."""
    name = "weact"
    label = 'WeAct Studio Display FS 3.5" [experimental]'
    size = (480, 320)                 # paisagem (nativa 320x480)
    experimental = True
    fade_ms = 0                       # o firmware aceita uma transição de brilho em ms

    def __init__(self, device="", ser=None, **_):
        self.ser = ser or serial.Serial(device, 115200, timeout=1, write_timeout=10, rtscts=True)
        try:
            self.ser.reset_input_buffer()
        except Exception:
            pass
        self.ser.write(cmd(SYSTEM_VERSION | 0x80))
        r = self.ser.read(19)
        self.version = r[1:9].decode("ascii", "replace").strip("\0 ") if len(r) >= 9 else ""
        self.ser.write(cmd(SET_ORIENTATION, LANDSCAPE, fmt="B"))
        self.front = None
        self.brightness = None
        self._restore = None

    def set_brightness(self, pct):
        pct = max(0, min(100, int(pct)))
        if pct != self.brightness:
            self.ser.write(cmd(SET_BRIGHTNESS, round(pct * 255 / 100), self.fade_ms, fmt="BH"))
            self.brightness = pct

    def off(self):
        self._restore = self.brightness
        self.set_brightness(0)
        self.ser.write(cmd(FREE))
        self.front = None

    def on(self):
        self.brightness = None
        self.set_brightness(self._restore or 60)

    def _blit(self, buf, x0, y0, x1, y1):
        self.ser.write(cmd(SET_BITMAP, x0, y0, x1 - 1, y1 - 1, fmt="HHHH"))
        data = np.ascontiguousarray(buf[y0:y1, x0:x1]).tobytes()
        step = (x1 - x0) * 4
        for i in range(0, len(data), step):
            self.ser.write(data[i:i + step])

    def show(self, img, full=False):
        w, h = self.size
        buf = rgb565_le(np.asarray(img.convert("RGB")))
        if full or self.front is None:
            self._blit(buf, 0, 0, w, h)
            self.front = buf
            return w * h
        diff = buf != self.front
        if not diff.any():
            return 0
        t = min(TILE, w, h)
        if w % t or h % t:            # telas pequenas: manda a faixa de linhas que mudou
            ys = np.flatnonzero(diff.any(axis=1))
            y0, y1 = ys[0], ys[-1] + 1
            self._blit(buf, 0, y0, w, y1)
            self.front = buf
            return w * (y1 - y0)
        from byorzin_monitor.display.backends.turing_a import _rects
        tiles = diff.reshape(h // t, t, w // t, t).any(axis=(1, 3))
        sent = 0
        for x0, y0, x1, y1 in _rects(tiles):
            self._blit(buf, x0 * t, y0 * t, x1 * t, y1 * t)
            sent += (x1 - x0) * (y1 - y0) * t * t
        self.front = buf
        return sent

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


class WeActMini(WeAct):
    """WeAct Studio Display FS 0.96" — experimental, não testado em hardware."""
    name = "weact-096"
    label = 'WeAct Studio Display FS 0.96" [experimental]'
    size = (160, 80)                  # paisagem (nativa 80x160)
