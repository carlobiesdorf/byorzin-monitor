# Efeitos de alerta na tela: moldura amarela pulsando quando uma sessão passa a esperar você e
# a comemoração quando uma sessão longa termina. Os alertas vêm prontos do coletor (`alerts` no
# /state); aqui só se decide por quanto tempo mostrar. Também o Byorzin do LLM local.
import math
import random
from functools import lru_cache

from byorzin_monitor.i18n import T

from PIL import ImageDraw

from byorzin_monitor.display import mascot as B
from byorzin_monitor.display.scenes import (BG, canvas, scale, DIM, GREEN, H, PANEL, TXT, W, YEL, F, ctext, fit, fmt_dur,
                                            host_color, idle_footer, paste, sprite)

LLM_NEON, LLM_GLOW = "#ff5ad8", "#ffc8f0"
DONE_SECONDS = 6
FRESH = 30       # alerta visto pela 1ª vez com mais idade que isso (display recém-aberto) é ignorado


def llm_sprite(size, mood, blink, viewbox):
    """Byorzin do LLM local, `size` px lógicos (na escala corrente: size*K)."""
    return _llm_sprite(size * scale(), mood, blink, viewbox)


@lru_cache(maxsize=64)
def _llm_sprite(size, mood, blink, viewbox):
    return B.render(size, mood=mood, gordura=0.3, neon=LLM_NEON, glow=LLM_GLOW, aneis=False,
                    blink=blink, viewbox=viewbox, acessorio="fones")


class AlertFX:
    """Guarda quando cada alerta foi visto pela primeira vez e diz qual efeito está ativo.
    Contar a partir de "visto aqui" (e não do horário do alerta) evita que o atraso da busca
    no coletor coma o efeito."""

    def __init__(self):
        self.seen = {}           # key -> instante em que a tela viu o alerta
        self.frame_until = 0
        self.done_until = 0
        self.done = None

    def update(self, v, cfg, now):
        for st in v.alive:
            for a in st.get("alerts") or []:
                k = a.get("key")
                if not k or k in self.seen:
                    continue
                self.seen[k] = now
                if now - (a.get("ts") or 0) > FRESH:
                    continue
                if a.get("type") == "waiting" and cfg.get("alert_screen", True):
                    self.frame_until = max(self.frame_until, now + cfg.get("alert_screen_seconds", 8))
                elif a.get("type") == "done" and cfg.get("done_celebrate", True):
                    self.done, self.done_until = {**a, "host": a.get("host") or st.get("host")}, now + DONE_SECONDS
        if len(self.seen) > 500:
            for k in sorted(self.seen, key=self.seen.get)[:250]:
                self.seen.pop(k)

    def force(self, kind, now, alert=None):
        if kind == "alert":
            self.frame_until = now + 8
        elif kind == "done":
            self.done, self.done_until = alert, now + DONE_SECONDS

    def framing(self, now):
        return now < self.frame_until

    def celebrating(self, now):
        return self.done if now < self.done_until else None

    def max_brightness(self, cfg, now):
        return cfg.get("alert_max_brightness", True) and (self.framing(now) or self.celebrating(now) is not None)

    def decorate(self, img, now, t):
        return alert_frame(img, t) if self.framing(now) else img


def alert_frame(img, t):
    """Moldura amarela pulsando (~1,2 Hz) por cima do quadro, sem cobrir o conteúdo."""
    img = img.copy()
    d = ImageDraw.Draw(img)            # desenho em pixels físicos: a espessura acompanha a escala
    sc = max(1, img.width // W)
    k = 0.5 + 0.5 * math.sin(t * 2 * math.pi * 1.2)
    col = tuple(int(c * (0.45 + 0.55 * k)) for c in YEL)
    w = (4 + int(3 * k)) * sc
    for i in range(w):
        d.rectangle([i, i, img.width - 1 - i, img.height - 1 - i], outline=col)
    return img


def scene_done(v, t, a):
    """Comemoração: Byorzin feliz pulando, confete e o nome da sessão que terminou."""
    im, d = canvas()
    rnd = random.Random(7)
    cols = [GREEN, YEL, (90, 200, 255), (255, 120, 220), (175, 135, 255)]
    for i in range(46):      # confete caindo
        x = rnd.uniform(0, W)
        sp = rnd.uniform(40, 90)
        y = (rnd.uniform(0, H) + t * sp) % (H - 40)
        r = rnd.choice((2, 3, 4))
        d.rectangle([x, y, x + r * 1.6, y + r], fill=cols[i % len(cols)])
    host = (a or {}).get("host")
    hop = abs(math.sin(t * 5)) * 14
    paste(im, sprite(220, "happy", 0.25, host, True, False, (0, 0), B.VB_ZOOM), W / 2, 112 - hop)
    d.rounded_rectangle([80, 222, 400, 286], radius=14, fill=PANEL, outline=host_color(host)[2] if host else GREEN)
    ctext(d, W / 2, 228, T("terminou!"), F(18), GREEN)
    label = (a or {}).get("label") or (a or {}).get("project") or T("sessão")
    line = f"{label}  @  {host}" if host else label
    ctext(d, W / 2, 251, fit(d, line, F(14), 300), F(14), TXT)
    if (a or {}).get("worked_s"):
        ctext(d, W / 2, 269, T("trabalhou {d}", d=fmt_dur(a["worked_s"])), F(11, False), DIM)
    idle_footer(d, v)
    return im
