# Tela no terminal: cada célula mostra 2 pixels na vertical com "▀" (cor de cima no texto,
# de baixo no fundo), em truecolor. Ajusta ao tamanho do terminal e só redesenha o que mudou.
import shutil
import sys

import numpy as np

from byorzin_monitor.display.backends.base import Backend

ESC = "\x1b["
HALF = "▀"


class Terminal(Backend):
    name = "terminal"
    label = "terminal (caracteres ▀ em truecolor)"
    save_frame = False

    def __init__(self, device="", out=None, cols=None, rows=None, **_):
        self.out = out or sys.stdout
        self._fixed = (cols, rows) if cols and rows else None   # testes: tamanho fixo
        self.front = None             # imagem (H x W x 3) desenhada por último
        self.quiet = self.out.isatty() and sys.stderr.isatty()
        # tela alternativa (devolve o terminal como estava ao sair) e cursor escondido
        self._write("\x1b[?1049h\x1b[?25l" + ESC + "2J")
        self._open = True

    @property
    def size(self):
        cols, rows = self._fixed or shutil.get_terminal_size((80, 24))
        return (max(1, cols), max(1, rows) * 2)

    def _write(self, s):
        self.out.write(s)
        self.out.flush()

    def show(self, img, full=False):
        a = np.asarray(img.convert("RGB"))
        if a.shape[0] % 2:            # altura ímpar: completa com preto
            a = np.vstack([a, np.zeros((1, a.shape[1], 3), a.dtype)])
        h, w = a.shape[:2]
        if full or self.front is None or self.front.shape != a.shape:
            self.front = None         # mudou o tamanho (ou pedido completo): redesenha tudo
            changed = np.ones((h // 2, w), bool)
            out = [ESC + "0m" + ESC + "2J"]
        else:
            d = (a != self.front).any(axis=2)
            changed = d[0::2] | d[1::2]
            out = []
        if not changed.any():
            return 0
        top, bot = a[0::2], a[1::2]
        sent = 0
        for row in np.flatnonzero(changed.any(axis=1)):
            cols = np.flatnonzero(changed[row])
            x0, x1 = cols[0], cols[-1] + 1       # um trecho por linha: do 1º ao último que mudou
            out.append(f"{ESC}{row + 1};{x0 + 1}H")
            last_fg = last_bg = None
            for fg, bg in zip(top[row, x0:x1].tolist(), bot[row, x0:x1].tolist()):
                if fg != last_fg:
                    out.append(f"{ESC}38;2;{fg[0]};{fg[1]};{fg[2]}m")
                    last_fg = fg
                if bg != last_bg:
                    out.append(f"{ESC}48;2;{bg[0]};{bg[1]};{bg[2]}m")
                    last_bg = bg
                out.append(HALF)
            sent += (x1 - x0) * 2
        out.append(ESC + "0m")
        self._write("".join(out))
        self.front = a
        return sent

    def off(self):
        self._write(ESC + "0m" + ESC + "2J")
        self.front = None

    def close(self):
        if getattr(self, "_open", False):
            self._open = False
            try:
                self._write(ESC + "0m\x1b[?25h\x1b[?1049l")
            except (OSError, ValueError):
                pass
