# Cenas do display (480x320). Cada função recebe a visão consolidada (View) e o tempo t,
# e devolve uma imagem PIL. O driver só envia à tela o que mudou entre quadros.
#
# Alta resolução: tudo é pensado em coordenadas lógicas 480x320, mas o quadro pode ser desenhado
# K vezes maior (escala por renderização, ver `scaled`): o canvas nasce em (480K x 320K), o
# `Draw` devolvido multiplica coordenadas, larguras de linha e raios por K, `F(sz)` devolve a fonte
# em sz*K (e `textlength` volta em unidades lógicas) e o Byorzin é rasterizado em size*K a partir
# do SVG. Com K=1 (tela USB, terminal, framebuffer) nada muda: é o ImageDraw puro de sempre.
import contextvars
import math
import os
import time
import zlib
from datetime import datetime
from collections import OrderedDict
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from byorzin_monitor.display import mascot as B
from byorzin_monitor.i18n import T, day_name, dec, plural

W, H = 480, 320
BG = (11, 13, 20); PANEL = (22, 26, 38); LINE = (40, 46, 64)
TXT = (232, 235, 242); DIM = (125, 133, 155); FAINT = (70, 74, 90)
CYAN = (90, 200, 255); GREEN = (90, 220, 140); YEL = (250, 200, 60); RED = (240, 90, 90); PURP = (175, 135, 255)

# cor por máquina: neon do Byorzin escolhido pelo nome da máquina (hash estável), a menos que o
# painel tenha definido outra (settings `colors`). A primeira é o verde neon do Byorzin.
PALETTE = ["#39ff88", "#b388ff", "#5ac8ff", "#ffb020", "#ff7a5c", "#c6ff4d"]
SYSTEM_FONT_DIR = "/usr/share/fonts/truetype/dejavu/"
BUNDLED_FONT_DIR = str(Path(__file__).resolve().parent / "fonts") + "/"


def _font_dir():
    """Fontes DejaVu do sistema (Linux, como sempre); sem elas (macOS), as que vêm no pacote."""
    if os.path.exists(SYSTEM_FONT_DIR + "DejaVuSans-Bold.ttf") and os.path.exists(SYSTEM_FONT_DIR + "DejaVuSans.ttf"):
        return SYSTEM_FONT_DIR
    return BUNDLED_FONT_DIR


FONT_DIR = _font_dir()


COLOR_OVERRIDE = {}     # host -> "#rrggbb" (painel); preenchido por set_colors()


def set_colors(colors):
    if colors != COLOR_OVERRIDE:
        COLOR_OVERRIDE.clear()
        COLOR_OVERRIDE.update(colors or {})


def _mix(hexc, frac):
    r, g, b = (int(hexc[i:i + 2], 16) for i in (1, 3, 5))
    return tuple(int(c + (255 - c) * frac) for c in (r, g, b))


def default_color(host):
    """Neon padrão da máquina: sempre o mesmo para o mesmo nome, em qualquer computador."""
    return PALETTE[zlib.crc32(str(host or "").encode()) % len(PALETTE)]


def host_color(host):
    """(neon, brilho, cor de texto/ponto) da máquina."""
    c = COLOR_OVERRIDE.get(host) or default_color(host)
    return (c, "#%02x%02x%02x" % _mix(c, 0.6), _mix(c, 0.25))


# ---------------------------------------------------------------- escala (alta resolução)
MAX_SCALE = 4
_SCALE = contextvars.ContextVar("byorzin_scale", default=1)   # por thread/renderização, não global


def clamp_scale(k):
    """Escala inteira entre 1 e MAX_SCALE (valor inválido vira 1)."""
    try:
        k = int(k)
    except (TypeError, ValueError):
        return 1
    return max(1, min(MAX_SCALE, k))


def scale():
    """Escala da renderização corrente (1 = 480x320, a tela USB)."""
    return _SCALE.get()


@contextmanager
def scaled(k):
    """Desenha o que estiver dentro do bloco K vezes maior (480K x 320K)."""
    tok = _SCALE.set(clamp_scale(k))
    try:
        yield _SCALE.get()
    finally:
        _SCALE.reset(tok)


def _flat(xy):
    """[x0, y0, x1, y1], [(x, y), ...] ou ((x, y), ...) -> lista plana de números."""
    out = []
    for p in xy:
        if isinstance(p, (tuple, list)):
            out.extend(p)
        else:
            out.append(p)
    return out


class HDDraw:
    """ImageDraw em coordenadas lógicas sobre um canvas K vezes maior.
    Caixas (retângulo, elipse) cobrem exatamente os pixels que cobririam em K=1, ampliados:
    x0 -> x0*K e x1 -> (x1+1)*K-1 (o PIL inclui as duas pontas). Linhas e polígonos passam pelo
    centro do bloco KxK de cada pixel lógico."""

    def __init__(self, draw, k):
        self.draw, self.k = draw, k

    def _box(self, xy):
        x0, y0, x1, y1 = _flat(xy)
        k = self.k
        return [x0 * k, y0 * k, (x1 + 1) * k - 1, (y1 + 1) * k - 1]

    def _pts(self, xy):
        f, k = _flat(xy), self.k
        c = (k - 1) / 2
        return [(f[i] * k + c, f[i + 1] * k + c) for i in range(0, len(f), 2)]

    def rectangle(self, xy, fill=None, outline=None, width=1):
        self.draw.rectangle(self._box(xy), fill=fill, outline=outline, width=width * self.k)

    def rounded_rectangle(self, xy, radius=0, fill=None, outline=None, width=1, **kw):
        self.draw.rounded_rectangle(self._box(xy), radius=radius * self.k, fill=fill, outline=outline,
                                    width=width * self.k, **kw)

    def ellipse(self, xy, fill=None, outline=None, width=1):
        self.draw.ellipse(self._box(xy), fill=fill, outline=outline, width=width * self.k)

    def line(self, xy, fill=None, width=1, joint=None):
        self.draw.line(self._pts(xy), fill=fill, width=max(1, width) * self.k, joint=joint)

    def polygon(self, xy, fill=None, outline=None, width=1):
        self.draw.polygon(self._pts(xy), fill=fill, outline=outline, width=width * self.k)

    def text(self, xy, text, fill=None, font=None, **kw):
        x, y = xy
        self.draw.text((x * self.k, y * self.k), text, fill=fill, font=font, **kw)

    def textlength(self, text, font=None, **kw):
        return self.draw.textlength(text, font=font, **kw) / self.k


def Draw(im):
    """ImageDraw do quadro na escala corrente (K=1: o ImageDraw puro, sem proxy)."""
    d = ImageDraw.Draw(im)
    k = scale()
    return d if k == 1 else HDDraw(d, k)


def canvas(color=None):
    """(imagem, draw) de um quadro novo na escala corrente: (480K x 320K), fundo BG."""
    k = scale()
    im = Image.new("RGB", (W * k, H * k), BG if color is None else color)
    return im, Draw(im)


@lru_cache(maxsize=None)
def _font(px, bold=True):
    return ImageFont.truetype(FONT_DIR + ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"), px)


def F(sz, bold=True):
    """Fonte de `sz` pontos lógicos (na escala corrente: sz*K pixels)."""
    return _font(sz * scale(), bold)


class _ByteLRU:
    """Cache LRU limitado por bytes (sprites grandes em escala alta pesam MBs cada)."""

    def __init__(self, budget):
        self.budget, self.used, self.d = budget, 0, OrderedDict()

    def get(self, key, make):
        im = self.d.get(key)
        if im is not None:
            self.d.move_to_end(key)
            return im
        im = make()
        n = im.width * im.height * len(im.getbands())
        self.d[key] = im
        self.used += n
        while self.used > self.budget and len(self.d) > 1:
            _, old = self.d.popitem(last=False)
            self.used -= old.width * old.height * len(old.getbands())
        return im


_HD_SPRITES = _ByteLRU(96 << 20)     # sprites em escala > 1 (a tela USB usa o lru_cache de sempre)


def sprite(size, mood="idle", gordura=0.25, host=None, aneis=True, blink=False, olhar=(0, 0), viewbox=B.VB_FULL):
    """Byorzin de `size` px lógicos (na escala corrente, rasterizado em size*K a partir do SVG)."""
    neon, glow = (host_color(host)[:2] if host else (None, None))
    k = scale()
    if k == 1:
        return _sprite(size, mood, gordura, neon, glow, aneis, blink, olhar, viewbox)
    key = (size * k, mood, gordura, neon, glow, aneis, blink, olhar, viewbox)
    return _HD_SPRITES.get(key, lambda: _sprite.__wrapped__(*key))


@lru_cache(maxsize=384)
def _sprite(size, mood, gordura, neon, glow, aneis, blink, olhar, viewbox):
    return B.render(size, mood=mood, gordura=gordura, neon=neon, glow=glow, aneis=aneis,
                    blink=blink, olhar=olhar, viewbox=viewbox)


def q(v, step=0.05):
    return round(round(v / step) * step, 2)


# ---------------------------------------------------------------- utilidades
def paste(im, spr, cx, cy):
    """Cola o sprite centrado em (cx, cy) lógicos."""
    k = scale()
    im.paste(spr, (int(cx * k - spr.width / 2), int(cy * k - spr.height / 2)), spr)


def ctext(d, cx, y, s, f, fill):
    d.text((cx - d.textlength(s, font=f) / 2, y), s, font=f, fill=fill)


def bar(d, x, y, w, h, pct, col, bg=LINE):
    d.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=bg)
    if pct > 0:
        d.rounded_rectangle([x, y, x + max(h, int(w * min(pct, 100) / 100)), y + h], radius=h // 2, fill=col)


def pct_color(p):
    return GREEN if p < 60 else YEL if p < 85 else RED


def fmt_tok(v):
    if v >= 1e9:
        return dec(f"{v / 1e9:.1f}B")
    if v >= 1e6:
        return dec(f"{v / 1e6:.1f}M")
    if v >= 1e3:
        return f"{v / 1e3:.0f}k"
    return str(int(v))


def fmt_dur(s):
    s = max(0, int(s))
    if s >= 86400:
        return f"{s // 86400}d {s % 86400 // 3600}h"
    if s >= 3600:
        return f"{s // 3600}h{s % 3600 // 60:02d}"
    return f"{s // 60} min"


def fmt_when(ts):
    dt = datetime.fromtimestamp(ts)
    return f"{day_name(dt.weekday())} {dt:%H:%M}"


def fmt_ago(ts):
    """'visto há': 40s, 12m, 3h, 2d."""
    s = max(0, int(time.time() - ts))
    return f"{s}s" if s < 60 else f"{s // 60}m" if s < 3600 else f"{s // 3600}h" if s < 86400 else f"{s // 86400}d"


_NOTDEF = None


@lru_cache(maxsize=4096)
def _drawable(ch):
    """A fonte DejaVu desenha este caractere? (compara com o glifo de "caractere ausente")."""
    global _NOTDEF
    f = _font(14)          # tamanho fixo: a resposta não depende da escala
    if _NOTDEF is None:
        m = f.getmask("\U0010FFFD")
        _NOTDEF = (m.size, bytes(m))
    m = f.getmask(ch)
    return (m.size, bytes(m)) != _NOTDEF


def clean(s):
    """Tira do texto o que a fonte da tela não desenha (emoji etc. viravam "□"). Acentos ficam.
    Símbolos ausentes somem; letras ausentes (ex.: CJK) viram "?"."""
    import unicodedata
    if not s:
        return s
    s = str(s)
    if s.isascii():
        # quebras de linha/tabs fazem o Pillow recusar medir o texto: viram espaço
        return " ".join(s.split()) if any(c < " " or c == "\x7f" for c in s) else s
    out = []
    for ch in s:
        cat = unicodedata.category(ch)
        if cat in ("Cf", "Cs", "Co") or 0xFE00 <= ord(ch) <= 0xFE0F or 0x1F3FB <= ord(ch) <= 0x1F3FF:
            continue                      # ZWJ, seletores de variação, tons de pele
        if cat.startswith("Z") or cat == "Cc":
            out.append(" ")
        elif cat.startswith("M") or _drawable(ch):
            out.append(ch)
        elif cat[0] in "LN":
            out.append("?")
    return " ".join("".join(out).split())


def fit(d, s, f, maxw):
    s = clean(s)
    while d.textlength(s, font=f) > maxw and len(s) > 3:
        s = s[:-2] + "…"
    return s


def blinking(t, seed=0, every=4.3):
    """Pisca ~0,18 s a cada `every` s, com fase diferente por seed."""
    return (t + seed * 1.7) % every < 0.18


# ---------------------------------------------------------------- várias contas
# Com uma conta só (o normal) nada disto é usado: as barras são as de sempre. Com 2+ contas, cada
# barra de limite vira uma por conta, com o rótulo (rodapés) ou o marcador curto (barra de cima).
def multi(v):
    return bool(getattr(v, "multi_account", False))


def acct_shown(v, key, n=3):
    """(contas a desenhar lado a lado, quantas ficaram de fora). Cabem até n; com mais, as n-1
    mais altas em `key` (mantendo a ordem de sempre) e um "+N"."""
    accs = v.accounts
    if len(accs) <= n:
        return accs, 0
    top = sorted(accs, key=lambda a: -(a[key] or 0))[:n - 1]
    return [a for a in accs if a in top], len(accs) - (n - 1)


def acct_tag(d, x, y, tag, col=DIM, f=None):
    """Marcador da conta (pílula com 1-2 letras); devolve a largura."""
    f = f or F(9)
    tw = d.textlength(tag, font=f)
    d.rounded_rectangle([x, y, x + tw + 8, y + 13], radius=6, outline=col)
    d.text((x + 4, y + 1), tag, font=f, fill=col)
    return tw + 8


def acct_cells(d, x0, x1, ty, by, bh, v, key, lf, pf, n=3, tags=False, dim=False):
    """Uma célula por conta entre x0 e x1: rótulo (ou marcador), barra e %."""
    accs, more = acct_shown(v, key, n)
    c = FAINT if dim else DIM
    if more:
        lab = f"+{more}"
        mw = d.textlength(lab, font=F(11)) + 6
        d.text((x1 - mw + 6, ty), lab, font=F(11), fill=c)
        x1 -= mw + 4
    cw = (x1 - x0) / max(1, len(accs))
    pw = d.textlength("100%", font=pf)
    for i, a in enumerate(accs):
        x = x0 + i * cw
        if tags:
            lw = acct_tag(d, x, by + bh / 2 - 7, a["tag"], c)
        else:
            lab = fit(d, a["label"] or "?", lf, min(cw * 0.4, 84))
            d.text((x, ty + 1), lab, font=lf, fill=c)
            lw = d.textlength(lab, font=lf)
        p = a[key]
        bx = x + lw + 5
        bw = max(12, cw - lw - pw - 14)
        if p is None:
            d.text((bx, ty), "–", font=pf, fill=c)
            continue
        bar(d, bx, by, bw, bh, p, (60, 90, 70) if dim else pct_color(p))
        d.text((bx + bw + 4, ty), f"{p:.0f}%", font=pf, fill=c if dim else TXT)


def topbar_rates_width(v):
    """Largura que as barras de 5h ocupam à direita da barra de cima (várias contas)."""
    n = len(v.accounts)
    shown = n if n <= 3 else 2
    return 20 + shown * (84 if shown <= 2 else 70) + (26 if n > 3 else 0)


# ---------------------------------------------------------------- blocos comuns
def topbar(d, v):
    d.rectangle([0, 0, W, 26], fill=PANEL)
    d.text((8, 4), datetime.now().strftime("%H:%M"), font=F(15), fill=TXT)
    x = 66
    seen = getattr(v, "host_seen", {})
    fh = v.five_hour
    mul = multi(v) and fh is not None
    limit = (W - 12 - topbar_rates_width(v)) if mul else (W - 156) if fh is not None else (W - 6)  # não invade as 5h
    hosts = list(v.hosts)
    for i, (h, up) in enumerate(hosts):
        col = host_color(h)[2] if up else FAINT
        lab = f"{h} {fmt_ago(seen[h])}" if not up and seen.get(h) else h   # offline: "notebook 2h"
        lab = clean(lab)
        more = len(hosts) - i - 1
        room = limit - (x + 13) - (30 if more else 0)
        if d.textlength(lab, font=F(12, False)) > room:
            if room < 40:                     # não cabe nem abreviado: "+N"
                d.text((x, 6), f"+{len(hosts) - i}", font=F(12), fill=DIM)
                break
            lab = fit(d, lab, F(12, False), room)
        d.ellipse([x, 9, x + 9, 18], fill=col)
        if not up and seen.get(h):
            d.ellipse([x + 2, 11, x + 7, 16], fill=PANEL)
        d.text((x + 13, 6), lab, font=F(12, False), fill=TXT if up else FAINT)
        x += 26 + d.textlength(lab, font=F(12, False))
    if mul:
        x0 = W - topbar_rates_width(v)
        d.text((x0, 6), "5h", font=F(12), fill=DIM)
        acct_cells(d, x0 + 20, W - 4, 7, 10, 7, v, "five_hour", F(10, False), F(11), tags=True)
    elif fh is not None:
        d.text((W - 150, 6), "5h", font=F(12), fill=DIM)
        bar(d, W - 128, 9, 80, 9, fh, pct_color(fh))
        d.text((W - 42, 6), f"{fh:.0f}%", font=F(12), fill=TXT)


def week_footer_multi(im, d, v, y0):
    """Rodapé grande com várias contas: uma linha por conta (rótulo, barra, %, renovação)."""
    d.text((12, y0 + 4), T("SEMANA"), font=F(10), fill=DIM)
    accs, more = acct_shown(v, "week_pct", 3)
    for i, a in enumerate(accs):
        y = y0 + 18 + i * 18
        d.text((12, y), fit(d, a["label"] or "?", F(12), 82), font=F(12), fill=TXT)
        p = a["week_pct"]
        if p is None:
            d.text((98, y), "–", font=F(12), fill=DIM)
            continue
        bar(d, 98, y + 3, 166, 10, p, pct_color(p))
        d.text((270, y - 1), f"{p:.0f}%", font=F(13), fill=TXT)
        if a["week_resets"]:
            d.text((312, y + 1), fmt_when(a["week_resets"]), font=F(10, False), fill=DIM)
    if more:
        d.text((12, y0 + 18 + 2 * 18), T("+{n} contas", n=more), font=F(12), fill=DIM)
    y = y0 + 18 + 3 * 18 + 3
    d.text((12, y), T("hoje {x}", x=fmt_tok(v.tok_today)), font=F(12), fill=TXT)
    d.text((130, y), T("semana {x}", x=fmt_tok(v.tok_week)), font=F(12), fill=TXT)


def week_footer(im, d, v, y0=228):
    d.rectangle([0, y0, W, H], fill=PANEL)
    if multi(v):
        week_footer_multi(im, d, v, y0)
        paste(im, sprite(70, "idle", q(v.fat), None, False, False, (0, 0), B.VB_BOT), W - 34, y0 + 26)
        return
    p = v.week_pct
    d.text((12, y0 + 10), T("SEMANA"), font=F(13), fill=DIM)
    if p is None:
        d.text((84, y0 + 9), T("aguardando a 1ª resposta da status line"), font=F(12, False), fill=DIM)
    else:
        bar(d, 84, y0 + 12, 280, 14, p, pct_color(p))
        d.text((372, y0 + 7), f"{p:.0f}%", font=F(22), fill=TXT)
    if v.week_resets:
        line = T("renova {when}  (em {dur})", when=fmt_when(v.week_resets), dur=fmt_dur(v.week_resets - time.time()))
        if v.rate_age > 600:
            line += T(" · visto há {dur}", dur=fmt_dur(v.rate_age))
        d.text((12, y0 + 40), line, font=F(12, False), fill=DIM)
    d.text((12, y0 + 64), T("hoje {x}", x=fmt_tok(v.tok_today)), font=F(14), fill=TXT)
    d.text((130, y0 + 64), T("semana {x}", x=fmt_tok(v.tok_week)), font=F(14), fill=TXT)
    rit = v.ritmo()
    if rit:
        txt, sub, ok = rit
        d.text((270, y0 + 64), txt, font=F(14), fill=GREEN if ok else RED)
        if sub:
            d.text((270 + d.textlength(txt, font=F(14)) + 6, y0 + 66), sub, font=F(11, False), fill=DIM)
    # Byorzin "barômetro": engorda com a semana
    paste(im, sprite(70, "idle", q(v.fat), None, False, False, (0, 0), B.VB_BOT), W - 34, y0 + 26)


def idle_footer(d, v, dim=False):
    c = FAINT if dim else DIM
    d.line([0, 292, W, 292], fill=LINE)
    d.text((10, 299), T("SEMANA"), font=F(11), fill=c)
    p = v.week_pct
    if multi(v):
        acct_cells(d, 72, W - 58, 299, 302, 9, v, "week_pct", F(10, False), F(12, False), dim=dim)
    elif p is not None:
        bar(d, 72, 302, 170, 9, p, (60, 90, 70) if dim else pct_color(p))
        txt = f"{p:.0f}%"
        if v.week_resets:
            txt += T(" · renova {when}", when=fmt_when(v.week_resets))
        d.text((250, 298), txt, font=F(12, False), fill=c)
    else:
        d.text((72, 298), T("hoje {a} · semana {b}", a=fmt_tok(v.tok_today), b=fmt_tok(v.tok_week)), font=F(12, False), fill=c)
    d.text((W - 48, 298), datetime.now().strftime("%H:%M"), font=F(12), fill=c)


# ---------------------------------------------------------------- cenas
TOOL_LABEL = {"Bash": "Bash", "Edit": "Edit", "Write": "Write", "MultiEdit": "Edit", "NotebookEdit": "Edit",
              "Read": "Read", "Grep": "Grep", "Glob": "Glob", "WebFetch": "Web", "WebSearch": "Web",
              "Agent": "Agente", "Task": "Agente", "TodoWrite": "Todo"}


def tool_name(tool, n=10):
    """Rótulo curto da ferramenta: MCP vira só a ação (mcp__servidor__acao → acao)."""
    if not tool:
        return ""
    if tool.startswith("mcp__"):
        tool = tool.split("__")[-1]
    lab = TOOL_LABEL.get(tool, tool[:n])
    return T(lab) if lab == "Agente" else lab


def session_look(s, t):
    """Humor do Byorzin e texto de status de uma sessão."""
    now = time.time()
    if s.get("mood") == "happy":
        return "happy", T("pronto!"), GREEN
    if s.get("mood") == "sad" or s["status"] in ("error", "limit"):
        return "sad", T("limite!") if s["status"] == "limit" else T("erro"), RED
    if s["status"] == "waiting":
        return "alert", T("esperando você"), YEL
    if s["status"] == "working" and s.get("kind") == "llm":
        return "thinking", T("gerando · {d}", d=fmt_dur(now - s["since"])), (255, 120, 220)
    if s["status"] == "working":
        tool = s.get("tool")
        subs = len(s.get("subagents") or [])
        if not tool and subs:
            return "thinking", T("{n} agente trabalhando · {d}" if subs == 1 else "{n} agentes trabalhando · {d}",
                                n=subs, d=fmt_dur(now - s["since"])), CYAN
        return "thinking", (tool_name(tool) if tool else T("pensando")) + f" · {fmt_dur(now - s['since'])}", CYAN
    idle = now - max(s.get("last") or 0, s["since"])
    return "idle", (T("ocioso · agora há pouco") if idle < 60 else T("ocioso há {d}", d=fmt_dur(idle))), DIM


def session_fat(tokens):
    # escala log: 100k → 0, 100M → 1
    if tokens <= 1e5:
        return 0.0
    return min(1.0, math.log10(tokens / 1e5) / 3)


def _gaze(t):
    pos = ((0, 0), (3, -1), (-3, 0), (2, 2), (-2, -2), (0, 1))
    return pos[int(t / 3.2) % len(pos)]


def scene_idle(v, t, kind):
    """kind: awake | sleepy | sleep | dream"""
    night = kind in ("sleep", "dream")
    im, d = canvas()
    mood = {"awake": "idle", "sleepy": "sleepy", "sleep": "sleep", "dream": "thinking"}[kind]
    look = _gaze(t) if kind == "awake" else (0, 0)
    blink = kind == "awake" and blinking(t)
    cx = 150 if kind == "dream" else W / 2
    paste(im, sprite(300, mood, q(v.fat), None, True, blink, look, B.VB_ZOOM), cx, 142)
    if kind == "sleepy":
        msg = T("sem sessões · agora há pouco") if v.idle_for < 60 else T("sem sessões há {d}", d=fmt_dur(v.idle_for))
        ctext(d, W / 2, 6, msg, F(12, False), DIM)
    if kind == "sleep":
        for i in range(3):   # Zzz subindo
            ph = (t / 3 + i / 3) % 1
            sz = 14 + int(ph * 16)
            d.text((300 + ph * 60, 120 - ph * 100), "Z", font=F(sz), fill=tuple(int(c * (1 - ph * 0.7)) for c in (168, 255, 201)))
    if kind == "dream" and v.dream:
        big, l1, l2 = v.dream
        for x, y, r in ((262, 150, 6), (280, 132, 9)):
            d.ellipse([x - r, y - r, x + r, y + r], fill=(40, 52, 48))
        d.rounded_rectangle([290, 20, 472, 132], radius=30, fill=(40, 52, 48))
        ctext(d, 381, 26, T("sonhando com..."), F(11, False), (170, 220, 190))
        ctext(d, 381, 46, big, F(26), (220, 255, 230))
        ctext(d, 381, 82, l1, F(12, False), (190, 230, 205))
        ctext(d, 381, 100, l2, F(12), GREEN)
    idle_footer(d, v, dim=night)
    if night:
        im = ImageEnhance.Brightness(im).enhance(0.6)
    return im


def scene_wake(v, t, s):
    im, d = canvas()
    paste(im, sprite(300, "alert", q(v.fat), None, True, False, (0, 0), B.VB_ZOOM), W / 2, 142)
    d.rounded_rectangle([100, 236, 380, 284], radius=12, fill=PANEL, outline=host_color(s["host"])[2])
    ctext(d, W / 2, 241, T("nova sessão"), F(11, False), DIM)
    ctext(d, W / 2, 258, fit(d, f"{s.get('label') or s['project']}  @  {s['host']}", F(15), 270), F(15), TXT)
    idle_footer(d, v)
    return im


def scene_limit(v, t):
    im, d = canvas()
    topbar(d, v)
    paste(im, sprite(200, "alert", 0.95, None, True, blinking(t), (0, 0), B.VB_ZOOM), 125, 125)
    fh, wk = v.five_hour or 0, v.week_pct or 0
    d.text((250, 60), "Byorzin", font=F(16), fill=TXT)
    d.text((250, 82), T("não aguenta"), font=F(16), fill=TXT)
    d.text((250, 104), T("mais tokens!"), font=F(16), fill=RED)
    y = 136
    if multi(v) and v.limit_account:          # várias contas: diz qual está no limite
        a = v.limit_account
        fh, wk = a["five_hour"] or 0, a["week_pct"] or 0
        d.text((250, y), fit(d, T("conta {x}", x=a["label"] or "?"), F(13), W - 258), font=F(13), fill=TXT)
        y += 22
        resets = a["five_resets"]
    else:
        resets = v.five_resets
    if fh >= wk and resets:
        d.text((250, y), T("5h em {p}%", p=f"{fh:.0f}"), font=F(13), fill=pct_color(fh))
        d.text((250, y + 20), T("renova {t}", t=f"{datetime.fromtimestamp(resets):%H:%M}"), font=F(12, False), fill=DIM)
        d.text((250, y + 38), T("(em {d})", d=fmt_dur(resets - time.time())), font=F(12, False), fill=DIM)
    else:
        d.text((250, y), T("semana em {p}%", p=f"{wk:.0f}"), font=F(13), fill=pct_color(wk))
    week_footer(im, d, v)
    return im


def scene_host(v, t, host, m):
    im, d = canvas()
    topbar(d, v)
    hc = host_color(host)[2]
    d.text((12, 36), host, font=F(18), fill=hc)
    sub = []
    if m.get("uptime_s"):
        sub.append(f"up {fmt_dur(m['uptime_s'])}")
    if m.get("cores"):
        sub.append(T("{n} núcleos", n=m["cores"]))
    if m.get("cpu_temp"):
        sub.append(f"CPU {m['cpu_temp']:.0f}°C")
    d.text((22 + d.textlength(host, font=F(18)), 41), " · ".join(sub), font=F(11, False), fill=DIM)
    rows = []
    if m.get("cpu") is not None:
        rows.append(("CPU", m["cpu"], f"{m['cpu']:.0f}%"))
    if m.get("ram_total_gb"):
        rows.append(("RAM", 100 * m["ram_used_gb"] / m["ram_total_gb"], dec(f"{m['ram_used_gb']:.1f} / {m['ram_total_gb']:.0f} GB")))
    g = m.get("gpu")
    if g:
        rows.append(("GPU", g["util"], f"{g['util']:.0f}%  {g['temp']:.0f}°C"))
        rows.append(("VRAM", 100 * g["mem_used_gb"] / g["mem_total_gb"], dec(f"{g['mem_used_gb']:.1f} / {g['mem_total_gb']:.0f} GB")))
    for i, (k, p, txt) in enumerate(rows):
        y = 70 + i * 30
        d.text((12, y), k, font=F(13), fill=DIM)
        bar(d, 70, y + 3, 230, 12, p, pct_color(p))
        d.text((312, y), txt, font=F(13, False), fill=TXT)
    y = 80 + len(rows) * 30
    d.line([12, y - 6, W - 12, y - 6], fill=LINE)
    if "ollama" in m:
        d.text((12, y), "Ollama", font=F(13), fill=DIM)
        ol = m["ollama"]
        txt = ", ".join(f"{x['name']} (" + dec(f"{x['vram_gb']:.1f}") + " GB)" for x in ol) if ol else T("nenhum modelo carregado")
        d.text((90, y), fit(d, txt, F(13, False), W - 100), font=F(13, False), fill=TXT if ol else DIM)
        y += 24
    dk = m.get("docker")
    if dk:
        d.text((12, y), "Docker", font=F(13), fill=DIM)
        run = T("{n} rodando", n=dk["running"])
        d.text((90, y), run, font=F(13), fill=GREEN)
        x = 90 + d.textlength(run, font=F(13))
        d.text((x, y), T(" · {n} parados", n=dk["stopped"]), font=F(13, False), fill=DIM)
        if dk.get("problem"):
            y += 22
            d.text((90, y), fit(d, T("com problema: ") + ", ".join(dk["problem"]), F(12, False), W - 100), font=F(12, False), fill=RED)
    idle_footer(d, v)
    return im
