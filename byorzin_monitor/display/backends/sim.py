# Tela simulada para testes: grava os quadros em PNG, sem hardware.
#   --device quadro.png  -> sobrescreve sempre o mesmo arquivo
#   --device pasta/      -> um arquivo por quadro (quadro-00001.png, ...), até `keep` quadros
from pathlib import Path

from byorzin_monitor.display.backends.base import Backend


class Sim(Backend):
    name = "sim"
    label = "simulada (grava PNG)"
    save_frame = False

    def __init__(self, device="", size=(480, 320), keep=500, **_):
        self.path = Path(device or "byorzin-sim.png")
        if isinstance(size, str):                       # "320x480"
            size = tuple(int(x) for x in size.lower().split("x"))
        self.size = tuple(size)
        self.keep = keep
        self.single = self.path.suffix.lower() == ".png"
        if not self.single:
            self.path.mkdir(parents=True, exist_ok=True)
        self.count = 0
        self.brightness = None
        self.is_on = True
        self.last = None

    def show(self, img, full=False):
        if img.size != self.size:
            raise ValueError(f"quadro {img.size} não cabe na tela simulada {self.size}")
        if not full and self.last is not None and img.tobytes() == self.last:
            return 0
        self.last = img.tobytes()
        self.count += 1
        if self.single:
            tmp = self.path.with_suffix(".tmp.png")
            img.save(tmp)
            tmp.replace(self.path)
        elif self.count <= self.keep:
            img.save(self.path / f"quadro-{self.count:05d}.png")
        return self.size[0] * self.size[1]

    def set_brightness(self, pct):
        self.brightness = pct

    def on(self):
        self.is_on = True

    def off(self):
        self.is_on = False
