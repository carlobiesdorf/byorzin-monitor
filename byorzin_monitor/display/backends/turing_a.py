# Driver do Turing Smart Screen 3.5" (protocolo "revision A"). Ver docs/protocolo-turing-rev-a.md
import numpy as np
import serial

from byorzin_monitor.display.backends.base import Backend

DEFAULT_PORT = "/dev/serial/by-id/usb-Turing_UsbMonitor_USB35INCHIPSV2-if00"
W, H = 480, 320
TILE = 16

CLEAR, SCREEN_OFF, SCREEN_ON, SET_BRIGHTNESS, SET_ORIENTATION, DISPLAY_BITMAP = 102, 108, 109, 110, 121, 197
LANDSCAPE = 2


def rgb565(arr):
    a = arr.astype(np.uint16)
    return ((a[..., 0] & 0xF8) << 8) | ((a[..., 1] & 0xFC) << 3) | (a[..., 2] >> 3)


class TuringA(Backend):
    name = "turing-a"
    label = 'Turing Smart Screen 3.5" (rev A)'
    size = (W, H)

    def __init__(self, device="", ser=None, **_):
        # `ser` permite passar uma porta falsa nos testes
        self.ser = ser or serial.Serial(device or DEFAULT_PORT, 115200, timeout=1, write_timeout=10, rtscts=True)
        self.front = None            # o que está na tela agora (RGB565, H x W)
        self._resync()
        self._cmd(SCREEN_ON)
        self._cmd(SET_ORIENTATION, extra=bytes([LANDSCAPE + 100, 320 >> 8, 320 & 255, 480 >> 8, 480 & 255]) + bytes(5))
        self.brightness = None

    def _resync(self):
        """Se um processo anterior morreu no meio de um DISPLAY_BITMAP, a tela ainda espera pixels
        e passaria a ler nossos comandos como imagem. Uma tela cheia de zeros completa qualquer
        envio pendente; o excesso vira "comandos" só de zeros, que a tela ignora."""
        zeros = bytes(W * 8)
        for _ in range(H * 2 // 8 + 1):
            self.ser.write(zeros)
        self.ser.flush()

    def _cmd(self, c, x=0, y=0, ex=0, ey=0, extra=b""):
        self.ser.write(bytes([x >> 2, ((x & 3) << 6) + (y >> 4), ((y & 15) << 4) + (ex >> 6),
                              ((ex & 63) << 2) + (ey >> 8), ey & 255, c]) + extra)

    def set_brightness(self, pct):
        pct = max(0, min(100, int(pct)))
        if pct != self.brightness:
            self._cmd(SET_BRIGHTNESS, x=int(255 - pct * 2.55))
            self.brightness = pct

    def off(self):
        self._cmd(SCREEN_OFF)
        self.front = None

    def on(self):
        self._cmd(SCREEN_ON)

    def _blit(self, buf, x0, y0, x1, y1):
        """Envia a região [x0,x1) x [y0,y1) do buffer RGB565."""
        data = np.ascontiguousarray(buf[y0:y1, x0:x1]).astype("<u2").tobytes()
        w = x1 - x0
        self._cmd(DISPLAY_BITMAP, x0, y0, x1 - 1, y1 - 1)
        step = w * 8
        for i in range(0, len(data), step):
            self.ser.write(data[i:i + step])

    def show(self, img, full=False):
        """Mostra uma imagem PIL 480x320, enviando só os retângulos que mudaram.
        Devolve o número de pixels enviados."""
        buf = rgb565(np.asarray(img.convert("RGB")))
        if full or self.front is None:
            self._blit(buf, 0, 0, W, H)
            self.front = buf
            return W * H
        diff = buf != self.front
        if not diff.any():
            return 0
        tiles = diff.reshape(H // TILE, TILE, W // TILE, TILE).any(axis=(1, 3))
        sent = 0
        for x0, y0, x1, y1 in _rects(tiles):
            self._blit(buf, x0 * TILE, y0 * TILE, x1 * TILE, y1 * TILE)
            sent += (x1 - x0) * (y1 - y0) * TILE * TILE
        self.front = buf
        return sent

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


def _rects(tiles):
    """Agrupa tiles sujos em retângulos: um intervalo por linha, juntando linhas consecutivas
    com o mesmo intervalo (ou quase), para não mandar muitos comandos pequenos."""
    rows = []
    for ty in range(tiles.shape[0]):
        xs = np.flatnonzero(tiles[ty])
        if len(xs):
            # quebra a linha em blocos separados por lacunas grandes (>= 4 tiles)
            start = prev = xs[0]
            for x in xs[1:]:
                if x - prev > 4:
                    rows.append((ty, start, prev + 1))
                    start = x
                prev = x
            rows.append((ty, start, prev + 1))
    rects = []
    for ty, a, b in rows:
        for r in rects:
            if r[3] == ty and r[0] <= a and b <= r[2] + 0 and (r[2] - r[0]) - (b - a) <= 3:
                r[3] = ty + 1
                break
            if r[3] == ty and abs(r[0] - a) <= 2 and abs(r[2] - b) <= 2:
                r[0], r[2], r[3] = min(r[0], a), max(r[2], b), ty + 1
                break
        else:
            rects.append([a, ty, b, ty + 1])
    return rects
