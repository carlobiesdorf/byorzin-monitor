# XuanFang 3.5" ("revision B" / "flagship"). EXPERIMENTAL: escrito a partir da documentação
# pública do protocolo, sem teste em hardware. Ver docs/telas.md.
#
# Protocolo: comandos de 10 bytes [CMD, 8 bytes de dados, CMD]; coordenadas em 16 bits
# big-endian com cantos inclusivos; pixels RGB565 big-endian logo depois do DISPLAY_BITMAP.
# Só o HELLO tem resposta (o byte 7 diz a sub-revisão e como o brilho funciona).
import time

import numpy as np
import serial

from byorzin_monitor.display.backends.base import Backend

W, H = 480, 320                       # em paisagem (nativa é 320x480 retrato)
TILE = 16
HELLO, SET_ORIENTATION, DISPLAY_BITMAP, SET_LIGHTING, SET_BRIGHTNESS = 0xCA, 0xCB, 0xCC, 0xCD, 0xCE
LANDSCAPE = 1
BITMAP_PAUSE = 0.05                   # sem essa pausa a tela corrompe o quadro seguinte


def packet(cmd, payload=b""):
    payload = bytes(payload)[:8]
    return bytes([cmd]) + payload + bytes(8 - len(payload)) + bytes([cmd])


def rgb565_be(arr):
    a = arr.astype(np.uint16)
    v = ((a[..., 0] & 0xF8) << 8) | ((a[..., 1] & 0xFC) << 3) | (a[..., 2] >> 3)
    return v.astype(">u2")


class TuringB(Backend):
    """XuanFang 3.5" rev B / flagship — experimental, não testado em hardware."""
    name = "turing-b"
    label = 'XuanFang 3.5" (rev B) [experimental]'
    size = (W, H)
    experimental = True

    def __init__(self, device="", ser=None, **_):
        self.ser = ser or serial.Serial(device, 115200, timeout=1, write_timeout=10, rtscts=True)
        self.subrev = self._hello()
        # sub-revisões 0x01/0x02 só ligam/desligam o brilho; 0x11/0x12 aceitam 0–255
        self.analog = self.subrev in (0x11, 0x12)
        self.ser.write(packet(SET_ORIENTATION, [LANDSCAPE]))
        self.front = None
        self.brightness = None

    def _hello(self):
        self.ser.write(packet(HELLO, b"HELLO"))
        r = self.ser.read(10)
        try:
            self.ser.reset_input_buffer()
        except Exception:
            pass
        if len(r) == 10 and r[0] == HELLO and r[9] == HELLO and r[1:6] == b"HELLO":
            return r[7]
        return 0x11                   # resposta inesperada: supõe brilho 0–255

    def set_brightness(self, pct):
        pct = max(0, min(100, int(pct)))
        if pct == self.brightness:
            return
        if self.analog:
            val = round(pct * 255 / 100)
        else:
            val = 0 if pct > 0 else 1   # 0 = aceso, 1 = apagado (invertido nessas sub-revisões)
        self.ser.write(packet(SET_BRIGHTNESS, [val]))
        self.brightness = pct

    def off(self):
        pct = self.brightness
        self.set_brightness(0)
        self._restore = pct
        self.front = None

    def on(self):
        self.brightness = None
        self.set_brightness(getattr(self, "_restore", None) or 60)

    def _blit(self, buf, x0, y0, x1, y1):
        c = [x0 >> 8, x0 & 255, y0 >> 8, y0 & 255, (x1 - 1) >> 8, (x1 - 1) & 255, (y1 - 1) >> 8, (y1 - 1) & 255]
        self.ser.write(packet(DISPLAY_BITMAP, c))
        data = np.ascontiguousarray(buf[y0:y1, x0:x1]).tobytes()
        step = (x1 - x0) * 8
        for i in range(0, len(data), step):
            self.ser.write(data[i:i + step])
        time.sleep(BITMAP_PAUSE)

    def show(self, img, full=False):
        """Imagem 480x320. Como cada envio custa uma pausa, manda um único retângulo:
        o que engloba todos os tiles que mudaram."""
        buf = rgb565_be(np.asarray(img.convert("RGB")))
        if full or self.front is None:
            self._blit(buf, 0, 0, W, H)
            self.front = buf
            return W * H
        diff = buf != self.front
        if not diff.any():
            return 0
        tiles = diff.reshape(H // TILE, TILE, W // TILE, TILE).any(axis=(1, 3))
        ys, xs = np.flatnonzero(tiles.any(axis=1)), np.flatnonzero(tiles.any(axis=0))
        x0, x1, y0, y1 = xs[0] * TILE, (xs[-1] + 1) * TILE, ys[0] * TILE, (ys[-1] + 1) * TILE
        self._blit(buf, x0, y0, x1, y1)
        self.front = buf
        return (x1 - x0) * (y1 - y0)

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass
