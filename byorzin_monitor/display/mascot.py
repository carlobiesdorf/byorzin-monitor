# Byorzin © BYOR-SEC — arte do mascote; uso permitido dentro deste projeto (ver LICENSE-ASSETS.md).
# Byorzin (mascote da BYOR-SEC) desenhado em SVG e rasterizado com cairosvg.
# Cores em atributos inline (cairosvg não entende var()), humor é parâmetro
# e há `gordura` (0..1) que alarga corpo, braços, pernas e sombra.
import io

from byorzin_monitor.sysinfo import prepare_cairo

prepare_cairo()     # macOS: acha o cairo do Homebrew (no Linux não faz nada)
import cairosvg  # noqa: E402
from PIL import Image, ImageChops, ImageDraw

CORES = dict(neon="#39ff88", glow="#a8ffc9", shell_hi="#eef8f8", shell="#b9d2d6", shell_lo="#6f8f95",
             joint="#1c272b", visor="#05090b", alert="#ffb020")
HUMORES = ("idle", "happy", "thinking", "alert", "sleepy", "sleep")


def _eye(cx, mood, glow, neon, blink):
    cy = 87
    if mood == "happy":
        return f'<path d="M{cx-5} {cy+2} Q{cx} {cy-5} {cx+5} {cy+2}" fill="none" stroke="{glow}" stroke-width="3.2" stroke-linecap="round"/>'
    if mood == "sleep" or blink:
        return f'<path d="M{cx-5} {cy+1} Q{cx} {cy+4} {cx+5} {cy+1}" fill="none" stroke="{glow}" stroke-width="3.2" stroke-linecap="round"/>'
    return (f'<circle cx="{cx}" cy="{cy}" r="8.5" fill="{neon}" opacity=".28"/>'
            f'<circle cx="{cx}" cy="{cy}" r="5.2" fill="{glow}"/>')


def svg(mood="idle", gordura=0.25, neon=None, glow=None, aneis=True, blink=False, olhar=(0, 0), viewbox="0 0 200 200", zzz=False, acessorio=None):
    c = dict(CORES)
    if neon: c["neon"] = neon
    if glow: c["glow"] = glow
    escudo = c["alert"] if mood == "alert" else c["neon"]
    f = max(0.0, min(1.0, gordura))
    bw = 15 + 47 * f                 # largura do corpo: 15 (magrinho) .. 62 (estufado); 24 ≈ normal
    bh = 29 + 9 * f
    bx = 100 - bw / 2
    dx = (bw - 24) / 2               # quanto braços se afastam
    lx = dx * 0.45                   # pernas abrem um pouco
    hw = 58 + 16 * f                 # bochechas: cabeça alarga levemente
    hx = 100 - hw / 2

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{viewbox}">',
           '<defs>',
           f'<radialGradient id="halo"><stop offset="0" stop-color="{escudo}" stop-opacity=".45"/>'
           f'<stop offset=".55" stop-color="{escudo}" stop-opacity=".16"/><stop offset="1" stop-color="{escudo}" stop-opacity="0"/></radialGradient>',
           f'<linearGradient id="shell" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{c["shell_hi"]}"/>'
           f'<stop offset=".55" stop-color="{c["shell"]}"/><stop offset="1" stop-color="{c["shell_lo"]}"/></linearGradient>',
           f'<linearGradient id="rim" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{c["neon"]}" stop-opacity=".55"/>'
           f'<stop offset=".35" stop-color="{c["neon"]}" stop-opacity="0"/><stop offset=".65" stop-color="{c["neon"]}" stop-opacity="0"/>'
           f'<stop offset="1" stop-color="{c["neon"]}" stop-opacity=".55"/></linearGradient>',
           f'<radialGradient id="visor" cx=".5" cy=".3" r=".8"><stop offset="0" stop-color="#16232a"/><stop offset="1" stop-color="{c["visor"]}"/></radialGradient>',
           '</defs>']
    if aneis:
        out.append('<circle cx="100" cy="100" r="96" fill="url(#halo)"/>')
    out.append(f'<ellipse cx="100" cy="181" rx="{26 + 14 * f}" ry="3.5" fill="{escudo}" opacity=".28"/>')
    if aneis:
        op = ".5" if mood == "sleep" else ".55" if mood == "sad" else "1"
        out.append(f'<g opacity="{op}">')
        for i in range(7):
            rx, ry, ang = 66 + i * 3.2, 52 + i * 2.2, i * 180 / 7
            out.append(f'<g transform="rotate({ang:.1f} 100 100)">'
                       f'<ellipse cx="100" cy="100" rx="{rx}" ry="{ry}" fill="none" stroke="{escudo}" stroke-width="6" opacity=".14"/>'
                       f'<ellipse cx="100" cy="100" rx="{rx}" ry="{ry}" fill="{escudo}" fill-opacity=".085" stroke="{escudo}" stroke-width="1.2" stroke-opacity=".75"/></g>')
        out.append('</g>')
    J = c["joint"]
    out.append('<g transform="translate(100 106) scale(.8) translate(-100 -106)">')
    # pernas
    for x0, jx in ((87.5 - lx, 94 - lx), (100.5 + lx, 106 + lx)):
        out.append(f'<circle cx="{jx}" cy="{139 + 2 * f}" r="3" fill="{J}"/>'
                   f'<rect x="{x0}" y="{141 + 2 * f}" width="12" height="15" rx="6" fill="url(#shell)"/>'
                   f'<rect x="{x0 + 1}" y="{154 + 2 * f}" width="10" height="4" rx="2" fill="{J}"/>')
    # braços (alerta: levantados; triste: caídos)
    rot = {"alert": (-28, 28), "sad": (10, -10), "happy": (-22, 22)}.get(mood, (4, -4))
    out.append(f'<g transform="translate({-dx} 0) rotate({rot[0]} 85 116)"><circle cx="85" cy="117" r="3.2" fill="{J}"/>'
               f'<path d="M84 118 L80 124 L83 125 Z" fill="{J}"/><ellipse cx="79" cy="128" rx="7.5" ry="6.5" fill="url(#shell)"/>'
               f'<path d="M74 132 l-1 4 M78 134 l0 4 M82 133 l1 3.5" stroke="{J}" stroke-width="1.6" stroke-linecap="round"/></g>')
    out.append(f'<g transform="translate({dx} 0) rotate({rot[1]} 115 116)"><circle cx="115" cy="117" r="3.2" fill="{J}"/>'
               f'<path d="M116 118 L120 124 L117 125 Z" fill="{J}"/><ellipse cx="121" cy="128" rx="7.5" ry="6.5" fill="url(#shell)"/>'
               f'<path d="M126 132 l1 4 M122 134 l0 4 M118 133 l-1 3.5" stroke="{J}" stroke-width="1.6" stroke-linecap="round"/></g>')
    # corpo
    out.append(f'<rect x="94" y="108" width="12" height="6" rx="2" fill="{J}"/>'
               f'<rect x="{bx}" y="111" width="{bw}" height="{bh}" rx="{min(bw, bh) / 2 - 1}" fill="url(#shell)"/>'
               f'<rect x="{bx}" y="111" width="{bw}" height="{bh}" rx="{min(bw, bh) / 2 - 1}" fill="url(#rim)"/>'
               f'<path d="M{bx + 3} {111 + bh * .52} Q100 {111 + bh * .52 + 4 + 4 * f} {bx + bw - 3} {111 + bh * .52}" fill="none" stroke="#5f7d83" stroke-width=".9"/>'
               f'<circle cx="100" cy="120" r="1.6" fill="{c["neon"]}" opacity=".9"/>')
    if f > 0.6:  # botões da barriga esticando
        out.append(f'<circle cx="100" cy="{125 + 3 * f}" r="1.1" fill="{J}"/><circle cx="100" cy="{131 + 3 * f}" r="1.1" fill="{J}"/>')
    # antena, orelhas
    ex = (hw - 60) / 2
    out.append(f'<path d="M{71 - ex} 82 L{68.5 - ex} 62" stroke="{J}" stroke-width="2" stroke-linecap="round"/>'
               f'<circle cx="{68.3 - ex}" cy="60.5" r="2.4" fill="{escudo}"/>'
               f'<rect x="{65.5 - ex}" y="77" width="9" height="19" rx="4.5" fill="{J}"/><rect x="{125.5 + ex}" y="77" width="9" height="19" rx="4.5" fill="{J}"/>'
               f'<circle cx="{70 - ex}" cy="86.5" r="1.4" fill="{c["neon"]}" opacity=".8"/><circle cx="{130 + ex}" cy="86.5" r="1.4" fill="{c["neon"]}" opacity=".8"/>')
    # cabeça + visor
    out.append(f'<rect x="{hx}" y="56" width="{hw}" height="54" rx="27" ry="25" fill="url(#shell)"/>'
               f'<rect x="{hx}" y="56" width="{hw}" height="54" rx="27" ry="25" fill="url(#rim)"/>'
               f'<path d="M100 56.5 L100 69" stroke="#6f8f95" stroke-width=".9"/>'
               f'<path d="M83 61 Q100 55 117 61" fill="none" stroke="#ffffff" stroke-opacity=".75" stroke-width="2.4" stroke-linecap="round"/>'
               f'<rect x="{75 - ex / 2}" y="70" width="{50 + ex}" height="34" rx="15.5" fill="url(#visor)"/>'
               f'<path d="M80 75 Q86 71.5 94 72" fill="none" stroke="#ffffff" stroke-opacity=".14" stroke-width="1.6" stroke-linecap="round"/>')
    if f > 0.7:  # bochechas coradas
        out.append(f'<ellipse cx="{82 - ex / 2}" cy="97" rx="3.5" ry="2" fill="#ff7a9a" opacity=".55"/>'
                   f'<ellipse cx="{118 + ex / 2}" cy="97" rx="3.5" ry="2" fill="#ff7a9a" opacity=".55"/>')
    # olhos
    gx, gy = olhar
    sc = {"alert": 1.18, "thinking": .88}.get(mood, 1)
    tx, ty = {"thinking": (3, -3), "sad": (0, 2)}.get(mood, (0, 0))
    out.append(f'<g transform="translate({gx + tx} {gy + ty}) translate(100 87) scale({sc}) translate(-100 -87)">'
               + _eye(89, mood, c["glow"], c["neon"], blink) + _eye(111, mood, c["glow"], c["neon"], blink) + '</g>')
    if mood == "sleepy":  # pálpebras retas a meio caminho
        out.append(f'<path d="M78 76 L100 76 L100 87 L78 87 Z M100 76 L122 76 L122 87 L100 87 Z" fill="{c["visor"]}"/>'
                   f'<path d="M81 87 L97 87 M103 87 L119 87" stroke="{c["glow"]}" stroke-width="1.6" stroke-linecap="round"/>')
    if mood == "sad":
        out.append(f'<path d="M81 78 L97 82 L97 86 L81 86 Z M119 78 L103 82 L103 86 L119 86 Z" fill="{c["visor"]}"/>')
    # boca
    N = c["neon"]
    boca = {
        "idle": f'<path d="M96.5 97 Q100 100 103.5 97" fill="none" stroke="{N}" stroke-width="1.8" stroke-linecap="round"/>',
        "happy": f'<path d="M94.5 96 Q100 96.8 105.5 96 Q104.5 101.5 100 101.5 Q95.5 101.5 94.5 96 Z" fill="{N}"/>',
        "thinking": f'<path d="M97 98.5 L103 98.5" fill="none" stroke="{N}" stroke-width="1.8" stroke-linecap="round"/>',
        "sleep": f'<path d="M97 98.5 L103 98.5" fill="none" stroke="{N}" stroke-width="1.8" stroke-linecap="round"/>',
        "sleepy": f'<ellipse cx="100" cy="98.8" rx="1.6" ry="1.2" fill="none" stroke="{N}" stroke-width="1.5"/>',
        "sad": f'<path d="M96.5 99.8 Q100 97 103.5 99.8" fill="none" stroke="{N}" stroke-width="1.8" stroke-linecap="round"/>',
        "alert": f'<ellipse cx="100" cy="98.5" rx="2" ry="2.4" fill="none" stroke="{N}" stroke-width="1.8"/>',
    }[mood]
    out.append(boca)
    if f > 0.85:  # suando de tão cheio
        out.append(f'<path d="M{134 + ex} 66 q2.5 4 0 6 q-2.5 -2 0 -6 Z" fill="#7fd4ff"/>')
    if acessorio == "fones":  # LLM local: fone de ouvido sobre a cabeça
        out.append(f'<path d="M{68 - ex} 84 Q{68 - ex} 40 100 40 Q{132 + ex} 40 {132 + ex} 84" fill="none" stroke="{J}" stroke-width="4.5" stroke-linecap="round"/>'
                   f'<path d="M{70 - ex} 80 Q{70 - ex} 43 100 43 Q{130 + ex} 43 {130 + ex} 80" fill="none" stroke="{N}" stroke-width="1.3" opacity=".8"/>'
                   f'<rect x="{62 - ex}" y="74" width="13" height="24" rx="6" fill="{J}" stroke="{N}" stroke-width="1.6"/>'
                   f'<rect x="{125 + ex}" y="74" width="13" height="24" rx="6" fill="{J}" stroke="{N}" stroke-width="1.6"/>'
                   f'<circle cx="{68.5 - ex}" cy="86" r="2.6" fill="{N}"/><circle cx="{131.5 + ex}" cy="86" r="2.6" fill="{N}"/>')
    if mood == "thinking":
        out.append(f'<g fill="{c["glow"]}"><circle cx="128" cy="56" r="2.2"/><circle cx="135" cy="50" r="2.8"/><circle cx="143" cy="43" r="3.4"/></g>')
    if mood == "sleep" and zzz:
        out.append(f'<g fill="{c["glow"]}" font-family="DejaVu Sans" font-weight="700"><text x="128" y="60" font-size="9">Z</text>'
                   f'<text x="136" y="52" font-size="7">z</text><text x="142" y="45" font-size="6">z</text></g>')
    out.append('</g></svg>')
    return "".join(out)


# enquadramentos: robô inteiro com anéis, anéis cortados (robô maior) e só o robô
VB_FULL, VB_ZOOM, VB_BOT = "0 0 200 200", "30 30 140 140", "50 56 100 100"


def render(size, **kw):
    png = cairosvg.svg2png(bytestring=svg(**kw).encode(), output_width=size, output_height=size)
    im = Image.open(io.BytesIO(png)).convert("RGBA")
    if kw.get("viewbox", VB_FULL) != VB_FULL:  # some com as bordas cortadas do halo/anéis
        im.putalpha(ImageChops.multiply(im.getchannel("A"), _vinheta(size)))
    return im


def _vinheta(size):
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    steps = 24
    for i in range(steps):
        r = size / 2 * (1 - i / steps * 0.28)
        v = int(255 * min(1, (i + 1) / steps * 1.6))
        d.ellipse([size / 2 - r, size / 2 - r, size / 2 + r, size / 2 + r], fill=v)
    return m
