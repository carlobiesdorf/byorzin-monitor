# Framebuffer do Linux (/dev/fbN): telas SPI do Raspberry Pi, HDMI sem desktop.
# Resolução, bits por pixel e bytes por linha vêm de /sys/class/graphics/fbN/.
# 16 bpp = RGB565 (little-endian); 24 bpp = BGR; 32 bpp = BGRA.
import glob
import os
from pathlib import Path

import numpy as np

from byorzin_monitor.display.backends.base import Backend


def fb_info(sysfs):
    """(largura, altura, bpp, stride) lidos do sysfs do framebuffer."""
    sysfs = Path(sysfs)
    w, h = (int(x) for x in (sysfs / "virtual_size").read_text().strip().split(","))
    bpp = int((sysfs / "bits_per_pixel").read_text().strip())
    try:
        stride = int((sysfs / "stride").read_text().strip())
    except (OSError, ValueError):
        stride = w * bpp // 8
    return w, h, bpp, stride


def encode(arr, bpp):
    """Imagem RGB (H x W x 3, uint8) -> bytes por pixel no formato do framebuffer (H x W x n)."""
    if bpp == 16:
        a = arr.astype(np.uint16)
        v = ((a[..., 0] & 0xF8) << 8) | ((a[..., 1] & 0xFC) << 3) | (a[..., 2] >> 3)
        return v.astype("<u2").view(np.uint8).reshape(arr.shape[0], arr.shape[1], 2)
    if bpp == 24:
        return np.ascontiguousarray(arr[..., ::-1])
    if bpp == 32:
        out = np.full((arr.shape[0], arr.shape[1], 4), 255, np.uint8)
        out[..., :3] = arr[..., ::-1]
        return out
    raise RuntimeError(f"framebuffer com {bpp} bits por pixel não suportado (use 16, 24 ou 32)")


def is_fb_device(path):
    """True se `path` é um /dev/fbN de verdade (dispositivo de caractere)."""
    import stat
    try:
        return stat.S_ISCHR(os.stat(path).st_mode) and Path(path).name.startswith("fb")
    except OSError:
        return Path(str(path)).name.startswith("fb") and str(path).startswith("/dev/")


def list_framebuffers():
    """Framebuffers presentes: [{"device", "size", "bpp", "name"}]."""
    out = []
    for dev in sorted(glob.glob("/dev/fb[0-9]*")):
        sysfs = Path("/sys/class/graphics") / Path(dev).name
        try:
            w, h, bpp, _ = fb_info(sysfs)
            name = (sysfs / "name").read_text().strip() if (sysfs / "name").exists() else ""
        except (OSError, ValueError):
            continue
        out.append({"device": dev, "size": (w, h), "bpp": bpp, "name": name})
    return out


class Framebuffer(Backend):
    name = "framebuffer"
    label = "framebuffer Linux (/dev/fbN)"

    def __init__(self, device="", sysfs=None, size=None, bpp=None, **_):
        self.device = device or "/dev/fb0"
        if size:
            # arquivo comum no lugar do /dev/fbN (teste): tamanho e bpp informados (--size/--bpp)
            w, h = size
            self.bpp = bpp or 16
            self.stride = w * self.bpp // 8
            need = self.stride * h
            if not os.path.exists(self.device) or (not is_fb_device(self.device) and os.path.getsize(self.device) < need):
                with open(self.device, "ab") as f:
                    f.truncate(need)
        else:
            # `sysfs` permite testar com um arquivo comum no lugar do /dev/fbN
            if sysfs is None and not is_fb_device(self.device):
                raise RuntimeError(f"{self.device} não é um framebuffer (/dev/fbN). Para simular num arquivo, "
                                   "informe também --size LARGURAxALTURA e --bpp 16|24|32 (veja docs/telas.md)")
            sysfs = sysfs or Path("/sys/class/graphics") / Path(self.device).name
            try:
                w, h, self.bpp, self.stride = fb_info(sysfs)
            except OSError as e:
                raise RuntimeError(f"não consegui ler as medidas de {self.device} em {sysfs}: {e}") from None
        encode(np.zeros((1, 1, 3), np.uint8), self.bpp)      # bpp não suportado: falha já aqui
        self.size = (w, h)
        self.bytespp = self.bpp // 8
        self.label = f"framebuffer {self.device} ({w}x{h}, {self.bpp} bpp)"
        self.f = open(self.device, "r+b", buffering=0)
        self.front = None

    def _write_rows(self, data, y0, y1):
        w = self.size[0]
        if self.stride == w * self.bytespp:
            os.lseek(self.f.fileno(), y0 * self.stride, os.SEEK_SET)
            self.f.write(data[y0:y1].tobytes())
            return
        for y in range(y0, y1):       # linhas com preenchimento no fim (stride maior)
            os.lseek(self.f.fileno(), y * self.stride, os.SEEK_SET)
            self.f.write(data[y].tobytes())

    def show(self, img, full=False):
        data = encode(np.asarray(img.convert("RGB")), self.bpp)
        if full or self.front is None:
            y0, y1 = 0, data.shape[0]
        else:
            rows = np.flatnonzero((data != self.front).any(axis=(1, 2)))
            if not len(rows):
                return 0
            y0, y1 = rows[0], rows[-1] + 1     # faixa de linhas que mudou
        self._write_rows(data, y0, y1)
        self.front = data
        return (y1 - y0) * self.size[0]

    def off(self):
        self.show(_black(self.size), full=True)

    def close(self):
        try:
            self.f.close()
        except Exception:
            pass


def _black(size):
    from PIL import Image
    return Image.new("RGB", size, (0, 0, 0))
