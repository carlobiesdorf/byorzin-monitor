#!/usr/bin/env python3
"""Gera as imagens do README (docs/img/) a partir do cenário demo — sem dados reais.

    python scripts/readme_images.py [--lang en|pt-BR] [--out docs/img] [--scale 2]

Os quadros são desenhados direto em alta resolução (scenes.scaled: 480K x 320K), então saem
nítidos sem ampliar pixels. Gera:

- layout-<nome>.png e scene-<nome>.png (960x640 com --scale 2);
- mosaic.png com os 9 layouts;
- screen.gif: a telinha "viva" (subagentes aparecendo, alguém esperando você, terminou, dormindo
  e sonhando), ~720 px de largura;
- hero.png: a telinha numa moldura de aparelho ao lado de uma captura do painel
  (usa docs/img/panel-overview.png se existir; gere as capturas antes para o hero completo).
"""
import argparse
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402

from byorzin_monitor import i18n  # noqa: E402
from byorzin_monitor.display import scenes as S  # noqa: E402
from byorzin_monitor.display.demo import demo_view  # noqa: E402
from byorzin_monitor.display.effects import alert_frame, scene_done  # noqa: E402
from byorzin_monitor.display.layouts import LAYOUTS  # noqa: E402

GREEN = (57, 255, 136)
MAIN_LAYOUTS = ("cards", "foco", "equipe", "palco", "maquinas", "dashboard", "lista")


def save_png(im, path):
    """PNG RGB otimizado (paleta reduzida cria faixas no brilho e nos gradientes do mascote)."""
    im.convert("RGB").save(path, optimize=True)


def dream_view():
    v = demo_view({})
    ds = v.dreams()
    v.dream = next((d for d in ds if "token" in d[1]), ds[0])
    return v


def render(fn, k):
    with S.scaled(k):
        return fn()


# ------------------------------------------------------------------ GIF da telinha
def screen_frames(k, width):
    """Roteiro de ~9 s: trabalhando (subagentes chegando) -> esperando você -> terminou -> dorme -> sonha."""
    v = demo_view({})
    full = {s["id"]: copy.deepcopy(s.get("subagents") or []) for s in v.sessions}
    frames, fps = [], 8
    dt = 1 / fps

    def add(img, n=1):
        img = img.resize((width, width * 2 // 3), Image.LANCZOS) if img.width != width else img
        frames.extend([img] * n)

    def subs(step):         # step 0..3: quantos subagentes cada sessão já chamou
        for s in v.sessions:
            s["subagents"] = full[s["id"]][:step]
        for s in v.sessions:
            if s["status"] == "waiting":
                s["status"] = "working"

    t = 0.0
    for step in range(4):   # 3,2 s de trabalho, um subagente novo a cada 0,8 s
        subs(step)
        for _ in range(int(0.8 * fps)):
            add(render(lambda: LAYOUTS["cards"](v, t), k))
            t += dt
    v = demo_view({})       # agora alguém está esperando você (moldura amarela)
    for _ in range(int(1.6 * fps)):
        add(render(lambda: alert_frame(LAYOUTS["cards"](v, t), t), k))
        t += dt
    done = next(({"label": s["label"], "host": s["host"], "worked_s": 1380} for s in v.sessions
                 if s["host"] == "server"), {"label": v.sessions[0]["label"], "host": v.sessions[0]["host"]})
    for i in range(int(2.0 * fps)):
        add(render(lambda: scene_done(v, i * dt, done), k))
    for i in range(int(1.4 * fps)):
        add(render(lambda: S.scene_idle(v, i * dt * 2, "sleep"), k))
    dv = dream_view()
    img = render(lambda: S.scene_idle(dv, 0, "dream"), k)
    add(img, int(1.6 * fps))
    return frames, int(1000 / fps)


def save_gif(frames, ms, path, colors=192):
    # paleta única tirada de quadros de todas as fases: evita cintilação entre quadros e deixa
    # o amarelo do alerta e o confete com a cor certa
    pick = frames[::max(1, len(frames) // 12)]
    fw, fh = frames[0].width // 2, frames[0].height // 2
    sample = Image.new("RGB", (fw, fh * len(pick)))
    for i, f in enumerate(pick):
        sample.paste(f.resize((fw, fh), Image.NEAREST), (0, fh * i))
    pal = sample.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    q = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in frames]
    # junta quadros idênticos seguidos (duração somada)
    out, durs = [], []
    for f in q:
        if out and f.tobytes() == out[-1].tobytes():
            durs[-1] += ms
        else:
            out.append(f)
            durs.append(ms)
    out[0].save(path, save_all=True, append_images=out[1:], duration=durs, loop=0, optimize=True, disposal=1)


# ------------------------------------------------------------------ hero
def _font(px, bold=True):
    return ImageFont.truetype(S.FONT_DIR + ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"), px)


def _shadow(base, box, radius, blur, color=(0, 0, 0, 170), offset=(0, 18)):
    sh = Image.new("RGBA", base.size, (0, 0, 0, 0))
    x0, y0, x1, y1 = box
    ImageDraw.Draw(sh).rounded_rectangle([x0 + offset[0], y0 + offset[1], x1 + offset[0], y1 + offset[1]],
                                         radius=radius, fill=color)
    base.alpha_composite(sh.filter(ImageFilter.GaussianBlur(blur)))


def _round(im, r):
    m = Image.new("L", im.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, im.width - 1, im.height - 1], radius=r, fill=255)
    im = im.convert("RGBA")
    im.putalpha(m)
    return im


def hero(out, k=4):
    Wd, Hd = 1600, 800
    bg = Image.new("RGBA", (Wd, Hd), (8, 10, 14, 255))
    # brilho verde suave atrás da telinha e um segundo, mais fraco, atrás do painel
    glow = Image.new("RGBA", (Wd, Hd), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse([120, 260, 820, 860], fill=(57, 255, 136, 60))
    g.ellipse([900, -120, 1700, 520], fill=(57, 255, 136, 26))
    bg.alpha_composite(glow.filter(ImageFilter.GaussianBlur(140)))
    ov = Image.new("RGBA", (Wd, Hd), (0, 0, 0, 0))   # grade e textos numa camada, compostos por cima
    d = ImageDraw.Draw(ov)
    for x in range(0, Wd, 40):      # grade discreta
        d.line([(x, 0), (x, Hd)], fill=(255, 255, 255, 9))
    for y in range(0, Hd, 40):
        d.line([(0, y), (Wd, y)], fill=(255, 255, 255, 9))

    # título
    d.text((80, 64), "Byorzin Monitor", font=_font(60), fill=(236, 244, 240))
    d.text((82, 146), "Every Claude Code session and subagent,", font=_font(24, False), fill=(170, 186, 178))
    d.text((82, 180), "from all your computers, on one screen.", font=_font(24, False), fill=(170, 186, 178))
    d.rounded_rectangle([82, 234, 82 + 8, 234 + 8], radius=4, fill=GREEN)
    d.text((100, 228), "USB screen  ·  any browser  ·  terminal", font=_font(17, False),
           fill=(120, 140, 130))
    bg.alpha_composite(ov)

    # captura do painel (direita, atrás)
    pimg = out / "panel-overview.png"
    if pimg.exists():
        p = Image.open(pimg).convert("RGB")
        pw = 820
        p = p.resize((pw, round(p.height * pw / p.width)), Image.LANCZOS)
        p = p.crop((0, 0, pw, min(p.height, 512)))
        px, py = 720, 110
        _shadow(bg, (px, py, px + p.width, py + p.height + 34), 16, 30)
        win = Image.new("RGBA", (p.width, p.height + 34), (22, 26, 32, 255))
        wd = ImageDraw.Draw(win)
        for i, c in enumerate(((255, 95, 87), (254, 188, 46), (40, 200, 64))):
            wd.ellipse([16 + i * 22, 11, 28 + i * 22, 23], fill=c)
        wd.rounded_rectangle([110, 7, 520, 27], radius=10, fill=(32, 37, 45))
        wd.text((124, 9), "localhost:8788", font=_font(13, False), fill=(140, 150, 160))
        win.paste(p, (0, 34))
        win = _round(win, 14)
        bg.alpha_composite(win, (px, py))
        ol = Image.new("RGBA", (Wd, Hd), (0, 0, 0, 0))
        ImageDraw.Draw(ol).rounded_rectangle([px, py, px + win.width - 1, py + win.height - 1], radius=14,
                                             outline=(255, 255, 255, 34), width=1)
        bg.alpha_composite(ol)

    # telinha 3.5" (esquerda, na frente), desenhada em alta resolução
    v = demo_view({})
    scr = render(lambda: LAYOUTS["cards"](v, 1.0), k)
    sw = 560
    scr = scr.resize((sw, sw * 2 // 3), Image.LANCZOS)
    bez, foot = 26, 0
    dw, dh = sw + 2 * bez, scr.height + 2 * bez + foot
    dx, dy = 90, 290
    _shadow(bg, (dx, dy, dx + dw, dy + dh), 30, 34, (0, 0, 0, 220), (0, 26))
    dev = Image.new("RGBA", (dw, dh), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dev)
    dd.rounded_rectangle([0, 0, dw - 1, dh - 1], radius=30, fill=(28, 31, 36))
    dd.rounded_rectangle([3, 3, dw - 4, dh - 4], radius=28, fill=(16, 18, 22))
    dd.rounded_rectangle([0, 0, dw - 1, dh - 1], radius=30, outline=(70, 76, 84), width=2)
    dev.paste(scr, (bez, bez))
    dd.rectangle([bez - 1, bez - 1, bez + sw, bez + scr.height], outline=(0, 0, 0), width=1)
    # reflexo sutil no vidro
    gl = Image.new("RGBA", (dw, dh), (0, 0, 0, 0))
    ImageDraw.Draw(gl).polygon([(bez, bez), (bez + sw * 0.55, bez), (bez + sw * 0.2, bez + scr.height),
                                (bez, bez + scr.height)], fill=(255, 255, 255, 10))
    dev.alpha_composite(gl)
    bg.alpha_composite(dev, (dx, dy))
    ImageDraw.Draw(bg).text((dx + dw - 140, dy + dh + 16), 'Turing 3.5" USB', font=_font(14, False),
                            fill=(110, 125, 118))
    save_png(bg.convert("RGB"), out / "hero.png")


def icon(out, px=256):
    """Ícone do README: o rosto do Byorzin com fundo transparente."""
    im = S.sprite(px, "happy", 0.25, None, False, False, (0, 0), "66 50 68 68")
    im.save(out / "icon.png", optimize=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="en")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "docs" / "img"))
    ap.add_argument("--scale", type=int, default=2, help="1..4 (2 = 960x640)")
    ap.add_argument("--only", choices=("screens", "gif", "hero"), help="gera só uma parte")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    i18n.set_lang(a.lang)
    k = S.clamp_scale(a.scale)
    t = 1.0

    if a.only in (None, "screens"):
        v = demo_view({})
        for name in MAIN_LAYOUTS:
            save_png(render(lambda: LAYOUTS[name](v, t), k), out / f"layout-{name}.png")
        save_png(render(lambda: S.scene_idle(v, t, "sleep"), k), out / "scene-sleep.png")
        dv = dream_view()
        save_png(render(lambda: S.scene_idle(dv, t, "dream"), k), out / "scene-dream.png")
        save_png(render(lambda: alert_frame(LAYOUTS["cards"](v, t), 0.2), k), out / "scene-alert.png")
        done = {"label": v.sessions[1]["label"], "host": v.sessions[1]["host"], "worked_s": 1380}
        save_png(render(lambda: scene_done(v, 0.3, done), k), out / "scene-done.png")

        # mosaico 3x3 com os 9 layouts (cada quadro 720x480)
        names, tw, th, gap = list(LAYOUTS), 720, 480, 16
        cols, rows = 3, (len(LAYOUTS) + 2) // 3
        mos = Image.new("RGB", (cols * tw + (cols + 1) * gap, rows * th + (rows + 1) * gap), (8, 10, 14))
        for i, name in enumerate(names):
            im = render(lambda: LAYOUTS[name](v, t), 2).resize((tw, th), Image.LANCZOS)
            mos.paste(im, (gap + (i % cols) * (tw + gap), gap + (i // cols) * (th + gap)))
        save_png(mos, out / "mosaic.png")

    if a.only in (None, "gif"):
        frames, ms = screen_frames(2, 720)
        save_gif(frames, ms, out / "screen.gif")

    if a.only in (None, "hero"):
        hero(out)
        icon(out)

    for p in sorted(out.iterdir()):
        print(f"{p.stat().st_size // 1024:5d} KB  {p.name}")


if __name__ == "__main__":
    main()
