# Layouts do modo trabalho (escolhido por `layout` no config.toml).
#   cards  — colunas: Byorzin grande por sessão, subagentes em fila embaixo
#   lista  — uma linha por sessão: rosto, nome, status e os subagentes com o que estão fazendo
#   foco   — a sessão mais importante em destaque + as demais em miniatura
#   equipe — organograma: sessões em cima, subagentes ligados embaixo
#   grade  — mosaico compacto (até 8 sessões), bom para muitas sessões abertas
#   palco  — Byorzins em pé num palco, com balões de fala do que estão fazendo
#   atividade — sessões à esquerda + feed ao vivo dos eventos à direita
#   dashboard — números (sessões, agentes, tokens, semana) + tokens por hora
#   maquinas  — uma faixa por computador (online/offline, visto há) com os Byorzins dele
import time
from datetime import datetime

from byorzin_monitor.display import mascot as B
from byorzin_monitor.i18n import T, is_en, plural
from byorzin_monitor.display.scenes import (BG, canvas, scale, CYAN, DIM, FAINT, GREEN, LINE, PANEL, PURP, RED, TOOL_LABEL, TXT, tool_name, YEL, H, W, F, bar, ctext,
                     fit, fmt_dur, fmt_tok, host_color, paste, pct_color, q, session_fat, session_look, sprite,
                     blinking, topbar, multi, acct_cells, acct_tag)

VB_HEAD = "66 50 68 68"
TOP, FOOT = 28, 294          # área útil entre a barra de cima e o rodapé compacto


def name(s):
    return s.get("label") or s["project"]


def host_line(s):
    """Máquina da sessão; com várias contas, também a conta ("server · Trabalho")."""
    return f"{s['host']} · {s['account_label']}" if s.get("account_label") else s["host"]


def status_col(s):
    return {"waiting": YEL, "working": CYAN, "error": RED, "limit": RED}.get(s["status"], DIM)


def sub_label(sub):
    tool = sub.get("tool")
    typ = sub_type(sub)
    return f"{typ} · {tool_name(tool)}" if tool else typ


def sub_type(sub):
    typ = sub.get("type") or T("agente")
    return T("geral") if typ == "general-purpose" else typ


def face(s, size, t, seed=0, head=True):
    mood, _, _ = session_look(s, t)
    blink = mood in ("idle", "thinking", "alert") and blinking(t, seed)
    if s.get("kind") == "llm":     # LLM local: Byorzin rosa de fone de ouvido
        from byorzin_monitor.display.effects import llm_sprite
        return llm_sprite(size, mood, blink, VB_HEAD if head else B.VB_BOT)
    return sprite(size, mood, q(session_fat(s.get("tokens", 0)), 0.1), s["host"], False, blink, (0, 0),
                  VB_HEAD if head else B.VB_BOT)


def sub_face(s, sub, size, t, seed, head=True):
    mood = "thinking" if sub.get("tool") else "idle"
    return sprite(size, mood, 0.15, s["host"], False, blinking(t, seed, 3.1), (0, 0), VB_HEAD if head else B.VB_BOT)


def mini_footer(d, v):
    d.rectangle([0, FOOT, W, H], fill=PANEL)
    y = FOOT + 7
    d.text((8, y - 1), T("SEMANA"), font=F(11), fill=DIM)
    p = v.week_pct
    if multi(v):          # várias contas: uma barra por conta, sem ritmo/hoje (não cabem)
        acct_cells(d, 70, W - 8, y - 1, y + 2, 9, v, "week_pct", F(10, False), F(12))
        return
    if p is not None:
        bar(d, 64, y + 2, 120, 9, p, pct_color(p))
        d.text((190, y - 2), f"{p:.0f}%", font=F(13), fill=TXT)
    x = 236
    rit = v.ritmo()
    if rit:
        d.text((x, y - 1), rit[0], font=F(11), fill=GREEN if rit[2] else RED)
        x += d.textlength(rit[0], font=F(11)) + 10
    d.text((x, y - 1), T("hoje {x}", x=fmt_tok(v.tok_today)), font=F(11, False), fill=DIM)


def ctx_bar(d, x, y, w, s, label=True, h=5):
    """Barra de uso do contexto da sessão (verde → amarelo → vermelho), com o % ao lado."""
    p = s.get("context_pct")
    if p is None:
        return
    if label:
        lab = f"ctx {p:.0f}%"
        lw = d.textlength(lab, font=F(9))
        bar(d, x, y, max(10, w - lw - 5), h, p, pct_color(p))
        d.text((x + w - lw, y - 3), lab, font=F(9), fill=DIM)
    else:
        bar(d, x, y, w, h, p, pct_color(p))


def chip(d, cx, y, host, f=None):
    f = f or F(10, False)
    hc = host_color(host)[2]
    tw = d.textlength(host, font=f)
    d.rounded_rectangle([cx - tw / 2 - 6, y, cx + tw / 2 + 6, y + 14], radius=7, outline=hc)
    ctext(d, cx, y + 1, host, f, hc)


def tool_badge(d, x, y, s, t):
    if s["status"] != "working" or not s.get("tool"):
        return
    lab = tool_name(s["tool"])
    w = d.textlength(lab, font=F(10))
    d.rounded_rectangle([x - w / 2 - 6, y, x + w / 2 + 6, y + 15], radius=7, fill=CYAN if (t % 1) < 0.5 else (60, 160, 210))
    ctext(d, x, y + 1, lab, F(10), BG)


def bang(d, x, y, t):
    if (t % 1) < 0.6:
        d.rounded_rectangle([x, y, x + 20, y + 20], radius=6, fill=YEL)
        ctext(d, x + 10, y, "!", F(15), BG)


def base(v):
    im, d = canvas()
    topbar(d, v)
    mini_footer(d, v)
    return im, d


# ---------------------------------------------------------------- 1. cards
def layout_cards(v, t):
    im, d = base(v)
    ss = v.sessions
    shown = ss[:4] if len(ss) <= 4 else ss[:3]
    n = len(shown) + (1 if len(ss) > 4 else 0)
    cw = W // n
    size = min(120, cw - 14)
    for i, s in enumerate(shown):
        x0, cx = cw * i, cw * i + cw // 2
        if i:
            d.line([x0, TOP + 6, x0, FOOT - 6], fill=LINE)
        _, status, scol = session_look(s, t)
        paste(im, face(s, size, t, i, head=False), cx, TOP + 6 + size // 2)
        tool_badge(d, cx + size * 0.3, TOP + size * 0.82, s, t)
        if s["status"] == "waiting":
            bang(d, cx + size * 0.22, TOP + 4, t)
        y = TOP + size + 10
        ctext(d, cx, y, fit(d, name(s), F(14), cw - 8), F(14), TXT)
        if s.get("sublabel"):
            ctext(d, cx, y + 18, fit(d, s["sublabel"], F(10, False), cw - 8), F(10, False), DIM)
        ctext(d, cx, y + 32, fit(d, status, F(11, False), cw - 6), F(11, False), scol)
        ctx_bar(d, cx - (cw - 24) / 2, y + 51, cw - 24, s)
        # subagentes: fila de rostinhos com a ferramenta embaixo
        subs = s.get("subagents") or []
        if subs:
            k = min(len(subs), max(1, (cw - 10) // 34))
            sx = cx - (k * 34) / 2 + 17
            for j, sub in enumerate(subs[:k]):
                paste(im, sub_face(s, sub, 30, t, i * 5 + j), sx + j * 34, y + 78)
                lab = tool_name(sub.get("tool"), 6)
                if lab:
                    ctext(d, sx + j * 34, y + 94, lab, F(9), CYAN)
            if len(subs) > k:
                d.text((x0 + cw - 22, y + 70), f"+{len(subs) - k}", font=F(10), fill=DIM)
        else:
            ctext(d, cx, y + 70, T("sem agentes"), F(10, False), FAINT)
    if len(ss) > 4:
        cx = cw * 3 + cw // 2
        d.line([cw * 3, TOP + 6, cw * 3, FOOT - 6], fill=LINE)
        ctext(d, cx, 110, f"+{len(ss) - 3}", F(30), DIM)
        ctext(d, cx, 150, T("sessões"), F(13, False), DIM)
    return im


# ---------------------------------------------------------------- 2. lista
def layout_lista(v, t):
    im, d = base(v)
    ss = v.sessions
    rows = 5
    rh = (FOOT - TOP) // rows
    shown = ss[:rows] if len(ss) <= rows else ss[:rows - 1]
    for i, s in enumerate(shown):
        y = TOP + i * rh
        if i % 2:
            d.rectangle([0, y, W, y + rh - 1], fill=(16, 19, 28))
        d.rectangle([0, y + 4, 3, y + rh - 5], fill=status_col(s))
        paste(im, face(s, rh - 6, t, i), 8 + (rh - 6) // 2, y + rh // 2)
        tx = rh + 8
        _, status, scol = session_look(s, t)
        hc = host_color(s["host"])[2]
        d.ellipse([tx, y + 10, tx + 7, y + 17], fill=hc)
        d.text((tx + 12, y + 5), fit(d, name(s), F(14), 300), font=F(14), fill=TXT)
        d.text((tx, y + 25), fit(d, status, F(12, False), 190), font=F(12, False), fill=scol)
        ctx_bar(d, tx, y + rh - 9, 186, s, h=4)
        if s["status"] == "waiting":
            bang(d, W - 30, y + 14, t)
        # subagentes à direita: rostinho + o que está fazendo
        subs = s.get("subagents") or []
        sx = tx + 196
        for j, sub in enumerate(subs[:3]):
            paste(im, sub_face(s, sub, 22, t, i * 5 + j), sx + 11, y + 34)
            lab = tool_name(sub.get("tool"), 5) or "…"
            d.text((sx + 23, y + 28), lab, font=F(10), fill=CYAN if sub.get("tool") else DIM)
            sx += 56
        if len(subs) > 3:
            d.text((sx, y + 28), f"+{len(subs) - 3}", font=F(10), fill=DIM)
        tok = s.get("tokens", 0)
        if tok and not subs:
            d.text((W - 70, y + 28), fmt_tok(tok), font=F(11, False), fill=FAINT)
    if len(ss) > rows:
        y = TOP + (rows - 1) * rh
        rest = ss[rows - 1:]
        busy = sum(1 for s in rest if s["status"] in ("working", "waiting"))
        d.text((16, y + 16), plural(len(rest), "+{n} sessão", "+{n} sessões") +
               (plural(busy, " · {n} ativa", " · {n} ativas") if busy else T(" ociosas")), font=F(13), fill=DIM)
        for j, s in enumerate(rest[:8]):
            paste(im, face(s, 28, t, 20 + j), 210 + j * 32, y + rh // 2)
    return im


# ---------------------------------------------------------------- 3. foco
class _Focus:
    idx = 0
    until = 0


def _pick_focus(ss, now):
    waiting = [s for s in ss if s["status"] == "waiting"]
    if waiting:
        return waiting[0]
    hot = [s for s in ss if s["status"] == "working"] or ss
    if now >= _Focus.until:
        _Focus.idx += 1
        _Focus.until = now + 8
    return hot[_Focus.idx % len(hot)]


def layout_foco(v, t):
    im, d = base(v)
    ss = v.sessions
    s = _pick_focus(ss, time.time())
    mood, status, scol = session_look(s, t)
    paste(im, face(s, 170, t, 0, head=False), 92, TOP + 92)
    tool_badge(d, 140, TOP + 150, s, t)
    if s["status"] == "waiting":
        bang(d, 140, TOP + 8, t)
    x = 190
    d.text((x, TOP + 8), fit(d, name(s), F(18), W - x - 8), font=F(18), fill=TXT)
    if s.get("sublabel"):
        d.text((x, TOP + 32), fit(d, s["sublabel"], F(11, False), W - x - 8), font=F(11, False), fill=DIM)
    d.text((x, TOP + 50), fit(d, status, F(15), W - x - 8), font=F(15), fill=scol)
    info = [host_line(s)]
    if s.get("model"):
        info.append(s["model"])
    if s.get("tokens"):
        info.append(f"{fmt_tok(s['tokens'])} tok")
    d.text((x, TOP + 74), fit(d, " · ".join(info), F(11, False), W - x - 8), font=F(11, False), fill=host_color(s["host"])[2])
    if s.get("context_pct") is not None:
        d.text((x, TOP + 94), T("contexto"), font=F(10), fill=DIM)
        bar(d, x + 58, TOP + 97, 120, 7, s["context_pct"], pct_color(s["context_pct"]))
        d.text((x + 184, TOP + 93), f"{s['context_pct']:.0f}%", font=F(10), fill=DIM)
    subs = s.get("subagents") or []
    d.text((x, TOP + 116), plural(len(subs), "{n} agente", "{n} agentes") if subs else T("sem agentes"),
           font=F(11), fill=TXT if subs else FAINT)
    for j, sub in enumerate(subs[:3]):
        yy = TOP + 136 + j * 26
        paste(im, sub_face(s, sub, 24, t, j), x + 12, yy + 10)
        d.text((x + 30, yy + 3), fit(d, sub_label(sub), F(11, False), W - x - 40), font=F(11, False),
               fill=CYAN if sub.get("tool") else DIM)
    if len(subs) > 3:
        d.text((x + 30, TOP + 214), plural(len(subs) - 3, "+{n} agente", "+{n} agentes"), font=F(10), fill=DIM)
    # demais sessões
    others = [o for o in ss if o is not s]
    d.line([0, 240, W, 240], fill=LINE)
    if others:
        for j, o in enumerate(others[:9]):
            cx = 26 + j * 50
            paste(im, face(o, 36, t, j + 1), cx, 262)
            d.ellipse([cx + 10, 274, cx + 18, 282], fill=status_col(o))
            ctext(d, cx, 280, fit(d, name(o), F(8, False), 48), F(8, False), DIM)
        if len(others) > 9:
            d.text((W - 26, 256), f"+{len(others) - 9}", font=F(11), fill=DIM)
    else:
        ctext(d, W / 2, 258, T("única sessão aberta"), F(11, False), FAINT)
    return im


# ---------------------------------------------------------------- 4. equipe
def layout_equipe(v, t):
    im, d = base(v)
    ss = v.sessions
    # até 3 sessões em colunas; com mais, 2 colunas + uma de resumo ("+N sessões"), como em cards
    shown = ss[:3] if len(ss) <= 3 else ss[:2]
    n = max(1, len(shown) + (1 if len(ss) > 3 else 0))
    cw = W // n
    for i, s in enumerate(shown):
        x0, cx = cw * i, cw * i + cw // 2
        if i:
            d.line([x0, TOP + 6, x0, FOOT - 6], fill=LINE)
        _, status, scol = session_look(s, t)
        paste(im, face(s, 74, t, i), cx, TOP + 42)
        if s["status"] == "waiting":
            bang(d, cx + 26, TOP + 4, t)
        ctext(d, cx, TOP + 80, fit(d, name(s), F(13), cw - 8), F(13), TXT)
        ctext(d, cx, TOP + 97, fit(d, status, F(11, False), cw - 8), F(11, False), scol)
        ctx_bar(d, cx - (cw - 40) / 2, TOP + 116, cw - 40, s)
        subs = s.get("subagents") or []
        if not subs:
            ctext(d, cx, TOP + 146, T("sem agentes"), F(10, False), FAINT)
            continue
        # tronco + galhos: cabem 3 agentes acima do rodapé; o resto vira "+N agentes"
        k = min(len(subs), 3)
        top_y = TOP + 126
        d.line([cx, top_y, cx, top_y + 10], fill=LINE, width=2)
        ys = [top_y + 26 + j * 36 for j in range(k)]
        d.line([x0 + 18, top_y + 10, x0 + 18, ys[-1]], fill=LINE, width=2)
        d.line([x0 + 18, top_y + 10, cx, top_y + 10], fill=LINE, width=2)
        for j, sub in enumerate(subs[:k]):
            y = ys[j]
            d.line([x0 + 18, y, x0 + 30, y], fill=LINE, width=2)
            paste(im, sub_face(s, sub, 30, t, i * 5 + j), x0 + 46, y)
            typ = sub_type(sub)
            d.text((x0 + 64, y - 14), fit(d, typ, F(11), cw - 70), font=F(11), fill=TXT)
            tool = sub.get("tool")
            d.text((x0 + 64, y + 1), fit(d, tool_name(tool) if tool else T("pensando"), F(10, False), cw - 70),
                   font=F(10, False), fill=CYAN if tool else DIM)
        if len(subs) > k:
            d.text((x0 + 30, ys[-1] + 18), plural(len(subs) - k, "+{n} agente", "+{n} agentes"), font=F(10), fill=DIM)
    if len(ss) > 3:
        x0 = cw * len(shown)
        cx = x0 + cw // 2
        rest = ss[len(shown):]
        d.line([x0, TOP + 6, x0, FOOT - 6], fill=LINE)
        ctext(d, cx, 96, f"+{len(rest)}", F(30), DIM)
        ctext(d, cx, 136, T("sessões"), F(13, False), DIM)
        busy = sum(1 for o in rest if o["status"] in ("working", "waiting"))
        ags = sum(len(o.get("subagents") or []) for o in rest)
        if busy:
            ctext(d, cx, 160, plural(busy, "{n} ativa", "{n} ativas"), F(11, False), CYAN)
        if ags:
            ctext(d, cx, 178, plural(ags, "{n} agente", "{n} agentes"), F(11, False), PURP)
        if any(o["status"] == "waiting" for o in rest):
            bang(d, cx - 10, 204, t)
    return im


# ---------------------------------------------------------------- 5. grade
def layout_grade(v, t):
    im, d = base(v)
    ss = v.sessions
    n = len(ss)
    cols, rows = (2, 1) if n <= 2 else (2, 2) if n <= 4 else (3, 2) if n <= 6 else (4, 2)
    tw, th = W // cols, (FOOT - TOP) // rows
    fs = min(th - 80, tw - 40, 104)
    shown = ss[:8] if n <= 8 else ss[:7]
    for i, s in enumerate(shown):
        x0, y0 = (i % cols) * tw, TOP + (i // cols) * th
        col = status_col(s)
        d.rounded_rectangle([x0 + 4, y0 + 4, x0 + tw - 4, y0 + th - 4], radius=10, fill=PANEL, outline=col,
                            width=2 if s["status"] in ("working", "waiting") else 1)
        cx = x0 + tw // 2
        paste(im, face(s, fs, t, i), cx, y0 + 10 + fs // 2)
        ty = y0 + fs - 58           # textos acompanham o tamanho do rosto
        if s["status"] == "waiting":
            bang(d, x0 + tw - 30, y0 + 8, t)
        subs = s.get("subagents") or []
        if subs:
            d.rounded_rectangle([x0 + 8, y0 + 8, x0 + 36, y0 + 24], radius=8, fill=PURP)
            ctext(d, x0 + 22, y0 + 9, f"×{len(subs)}", F(10), BG)
        ctext(d, cx, ty + 72, fit(d, name(s), F(12), tw - 14), F(12), TXT)
        _, status, scol = session_look(s, t)
        ctext(d, cx, ty + 90, fit(d, status, F(10, False), tw - 12), F(10, False), scol)
        ctext(d, cx, ty + 104, fit(d, host_line(s), F(9, False), tw - 16), F(9, False), host_color(s["host"])[2])
        ctx_bar(d, x0 + 14, ty + 119, tw - 28, s, h=4)
    if n > 8:
        x0, y0 = 3 * tw, TOP + th
        d.rounded_rectangle([x0 + 4, y0 + 4, x0 + tw - 4, y0 + th - 4], radius=10, outline=LINE)
        ctext(d, x0 + tw // 2, y0 + 36, f"+{len(ss) - 7}", F(26), DIM)
        ctext(d, x0 + tw // 2, y0 + 72, T("sessões"), F(11, False), DIM)
    return im


# ---------------------------------------------------------------- 6. palco
def _bubble(d, cx, y, text, col, maxw):
    f = F(10)
    text = fit(d, text, f, maxw - 12)
    w = d.textlength(text, font=f) + 12
    d.rounded_rectangle([cx - w / 2, y, cx + w / 2, y + 18], radius=8, fill=col)
    d.polygon([(cx - 4, y + 17), (cx + 4, y + 17), (cx, y + 23)], fill=col)
    ctext(d, cx, y + 2, text, f, BG)


def layout_palco(v, t):
    im, d = base(v)
    floor = 236
    for i in range(6):   # chão com leve gradiente
        d.rectangle([0, floor + i * 3, W, floor + i * 3 + 3], fill=(20 + i * 2, 24 + i * 2, 36 + i * 2))
    d.line([0, floor, W, floor], fill=LINE, width=2)
    ss = v.sessions[:4]
    n = max(1, len(ss))
    cw = W // n
    big = min(104, cw - 40)
    for i, s in enumerate(ss):
        subs = s.get("subagents") or []
        cx = cw * i + cw // 2 - (14 if subs else 0)
        spr = face(s, big, t, i, head=False)
        paste(im, spr, cx, floor - big // 2 + 4)
        for j, sub in enumerate(subs[:2]):
            paste(im, sub_face(s, sub, 46, t, i * 5 + j, head=False), cx + big // 2 + 4 + j * 22, floor - 20)
        mood, status, scol = session_look(s, t)
        if s["status"] == "waiting":
            txt, col = T("precisa de você!"), YEL
        elif s["status"] == "working":
            sub_tools = [tool_name(x.get("tool")) for x in subs if x.get("tool")]
            main = tool_name(s.get("tool")) if s.get("tool") else T("pensando…")
            txt, col = (main + (plural(len(subs), " +{n} agente", " +{n} agentes") if subs else "")), CYAN
        elif mood == "happy":
            txt, col = T("pronto!"), GREEN
        else:
            txt, col = "zzz", (90, 96, 115)
        bob = -2 if (s["status"] == "working" and (t * 2 + i) % 1 < 0.5) else 0
        _bubble(d, cx, floor - big - 22 + bob, txt, col, cw - 6)
        ctext(d, cw * i + cw // 2, floor + 16, fit(d, name(s), F(13), cw - 8), F(13), TXT)
        ctext(d, cw * i + cw // 2, floor + 32, fit(d, host_line(s), F(9, False), cw - 8), F(9, False), host_color(s["host"])[2])
        bw = min(cw - 24, 120)
        ctx_bar(d, cw * i + cw // 2 - bw / 2, floor + 48, bw, s, h=4)
    if len(v.sessions) > 4:
        lab = plural(len(v.sessions) - 4, "+{n} sessão", "+{n} sessões")
        d.text((W - 6 - d.textlength(lab, font=F(10)), TOP + 4), lab, font=F(10), fill=DIM)
    return im


# ---------------------------------------------------------------- 7. atividade
def _event_text(e):
    n, tool = e.get("hook_event_name"), e.get("tool_name")
    tool = tool_name(tool)
    who = T("agente · ") if e.get("sub") else ""
    at = e.get("agent_type") or ""
    return {
        "PreToolUse": (f"{who}{tool}", CYAN),
        "UserPromptSubmit": (T("nova mensagem"), TXT),
        "SubagentStart": (T("agente {t} começou", t=at), PURP),
        "SubagentStop": (T("agente {t} terminou", t=at), DIM),
        "Stop": (T("terminou ✓"), GREEN),
        "StopFailure": (T("falhou: {e}", e=e.get("error") or ""), RED),
        "PostToolUseFailure": (T("{tool} falhou", tool=who + tool), RED),
        "PermissionRequest": (T("pediu permissão"), YEL),
        "PermissionDenied": (T("permissão negada"), RED),
        "Notification": (T("esperando você") if e.get("notification_type") in ("permission_prompt", "idle_prompt") else T("aviso"), YEL),
        "SessionStart": (T("sessão aberta"), GREEN),
    }.get(n, (n or "?", DIM))


def _ago(ts):
    s = max(0, int(time.time() - ts))
    return f"{s}s" if s < 60 else f"{s // 60}m" if s < 3600 else f"{s // 3600}h"


def layout_atividade(v, t):
    im, d = base(v)
    lw = 196
    d.line([lw, TOP + 4, lw, FOOT - 4], fill=LINE)
    rows = 6
    # com mais de 6 sessões, a última linha vira o resumo "+N sessões" (nada por cima de nada)
    ss = v.sessions[:rows] if len(v.sessions) <= rows else v.sessions[:rows - 1]
    rh = (FOOT - TOP) // rows
    for i, s in enumerate(ss):
        y = TOP + i * rh
        d.rectangle([0, y + 5, 3, y + rh - 5], fill=status_col(s))
        paste(im, face(s, 34, t, i), 24, y + rh // 2)
        _, status, scol = session_look(s, t)
        subs = s.get("subagents") or []
        d.text((46, y + 6), fit(d, name(s), F(12), lw - (80 if subs else 52)), font=F(12), fill=TXT)
        d.text((46, y + 21), fit(d, status, F(10, False), lw - 52), font=F(10, False), fill=scol)
        ctx_bar(d, 46, y + 36, lw - 54, s, h=3)
        subs = s.get("subagents") or []
        if subs:
            d.text((lw - 26, y + 7), f"×{len(subs)}", font=F(10), fill=PURP)
    if len(v.sessions) > rows:
        y = TOP + (rows - 1) * rh
        rest = v.sessions[rows - 1:]
        busy = sum(1 for s in rest if s["status"] in ("working", "waiting"))
        d.text((10, y + 8), plural(len(rest), "+{n} sessão", "+{n} sessões"), font=F(12), fill=DIM)
        if busy:
            d.text((10, y + 24), plural(busy, "{n} ativa", "{n} ativas"), font=F(10, False), fill=CYAN)
        for j, s in enumerate(rest[:3]):
            paste(im, face(s, 26, t, 30 + j), 118 + j * 26, y + rh // 2)
    x = lw + 10
    d.text((x, TOP + 4), T("AGORA"), font=F(10), fill=DIM)
    evs = v.events[:12]
    if not evs:
        d.text((x, TOP + 30), T("sem eventos ainda"), font=F(11, False), fill=FAINT)
    for j, e in enumerate(evs):
        y = TOP + 22 + j * 20
        txt, col = _event_text(e)
        d.text((x, y), _ago(e.get("ts", 0)).rjust(3), font=F(10, False), fill=FAINT)
        hc = host_color(e.get("host"))[2]
        d.ellipse([x + 30, y + 4, x + 36, y + 10], fill=hc)
        proj = fit(d, e.get("label") or e.get("project") or "?", F(10), 78)
        d.text((x + 42, y), proj, font=F(10), fill=TXT)
        d.text((x + 126, y), fit(d, txt, F(10, False), W - x - 132), font=F(10, False), fill=col)
    return im


# ---------------------------------------------------------------- 8. dashboard
def _wk_sub(v):
    """Legenda do % da semana: "usado"; com várias contas, de qual conta é o maior."""
    if multi(v):
        a = max(v.accounts, key=lambda a: a["week_pct"] or 0)
        return a["label"] or T("usado")
    return T("usado")


def layout_dashboard(v, t):
    im, d = base(v)
    ss = v.sessions
    active = sum(1 for s in ss if s["status"] in ("working", "waiting"))
    agents = sum(len(s.get("subagents") or []) for s in ss)
    waiting = sum(1 for s in ss if s["status"] == "waiting")
    p = v.week_pct
    kpis = [
        (T("SESSÕES"), f"{active}/{len(ss)}", T("ativas"), CYAN),
        (T("AGENTES"), str(agents), T("rodando"), PURP),
        (T("HOJE"), fmt_tok(v.tok_today), T("tokens"), TXT),
        (T("SEMANA"), f"{p:.0f}%" if p is not None else "–",
         _wk_sub(v), pct_color(p or 0)),
    ]
    kw = W // 4
    for i, (lab, val, sub, col) in enumerate(kpis):
        x0 = i * kw
        d.rounded_rectangle([x0 + 5, TOP + 4, x0 + kw - 5, TOP + 74], radius=10, fill=PANEL)
        ctext(d, x0 + kw / 2, TOP + 10, lab, F(10), DIM)
        ctext(d, x0 + kw / 2, TOP + 26, val, F(24), col)
        ctext(d, x0 + kw / 2, TOP + 56, sub, F(9, False), DIM)
    if waiting and (t % 1) < 0.6:
        d.rounded_rectangle([kw - 30, TOP + 8, kw - 10, TOP + 26], radius=6, fill=YEL)
        ctext(d, kw - 20, TOP + 8, "!", F(13), BG)
    # tokens por hora (24 h)
    gx, gy, gw, gh = 14, TOP + 98, W - 28, 76
    d.text((gx, TOP + 82), T("tokens por hora · últimas 24h"), font=F(10), fill=DIM)
    hv = v.hourly or [0] * 24
    mx = max(hv) or 1
    bw = gw / len(hv)
    cur_h = datetime.now().hour
    for i, val in enumerate(hv):
        h = int(gh * val / mx)
        x = gx + i * bw
        col = CYAN if i == len(hv) - 1 else (60, 120, 160)
        if h:
            d.rectangle([x + 1, gy + gh - h, x + bw - 2, gy + gh], fill=col)
        if (cur_h - (len(hv) - 1 - i)) % 6 == 0:
            d.text((x, gy + gh + 2), f"{(cur_h - (len(hv) - 1 - i)) % 24}h", font=F(8, False), fill=FAINT)
    d.text((W - 80, TOP + 82), T("pico {x}", x=fmt_tok(mx)), font=F(9, False), fill=FAINT)
    # rostos das sessões
    y = 268
    vis = ss[:12] if len(ss) <= 12 else ss[:11]     # com mais de 12, o 12º lugar vira "+N"
    for j, s in enumerate(vis):
        cx = 22 + j * 38
        paste(im, face(s, 30, t, j), cx, y)
        d.ellipse([cx + 8, y + 9, cx + 15, y + 16], fill=status_col(s))
        ctx_bar(d, cx - 14, y + 19, 28, s, label=False, h=3)
    if len(ss) > 12:
        ctext(d, 22 + 11 * 38, y - 8, f"+{len(ss) - 11}", F(13), DIM)
    if not ss:
        ctext(d, W / 2, y - 6, T("nenhuma sessão aberta"), F(11, False), FAINT)
    return im


# ---------------------------------------------------------------- 9. máquinas
_DIM_FACES = {}


def _offline_face(size, host):
    """Rosto dormindo e apagado para sessões de máquina fora do ar (cacheado)."""
    k = (size, host, scale())
    if k not in _DIM_FACES:
        from PIL import ImageEnhance
        spr = sprite(size, "sleep", 0.1, host, False, False, (0, 0), VB_HEAD)
        _DIM_FACES[k] = ImageEnhance.Brightness(spr).enhance(0.45)
    return _DIM_FACES[k]


def layout_maquinas(v, t):
    """Uma faixa por computador: online/offline, sessões e os Byorzins de cada uma."""
    from byorzin_monitor.display.scenes import fmt_ago
    im, d = base(v)
    ms = getattr(v, "machines", None) or [{"name": h, "online": up, "seen": None, "sessions": [s for s in v.sessions if s["host"] == h],
                                           "metrics": {}} for h, up in v.hosts]
    if not ms:
        ctext(d, W / 2, 140, T("nenhuma máquina"), F(14), FAINT)
        return im
    rows = min(len(ms), 4)
    shown = ms if len(ms) <= 4 else ms[:3]
    rh = (FOOT - TOP) // rows
    lw = 132
    for i, m in enumerate(shown):
        y = TOP + i * rh
        on, ss = m["online"], m["sessions"]
        hc = host_color(m["name"])[2] if on else FAINT
        if i % 2:
            d.rectangle([0, y, W, y + rh - 1], fill=(16, 19, 28))
        d.rectangle([0, y + 4, 3, y + rh - 5], fill=hc)
        d.ellipse([10, y + 9, 19, y + 18], fill=hc if on else BG, outline=hc, width=2)
        acc = getattr(v, "host_account", {}).get(m["name"]) if on else None
        tagw = d.textlength(acc["tag"], font=F(9)) + 12 if acc else 0
        nm = fit(d, m["name"], F(14), lw - 28 - tagw)
        d.text((25, y + 4), nm, font=F(14), fill=TXT if on else DIM)
        if acc:
            acct_tag(d, 25 + d.textlength(nm, font=F(14)) + 5, y + 6, acc["tag"])
        if on:
            act = sum(1 for s in ss if s["status"] in ("working", "waiting"))
            ags = sum(len(s.get("subagents") or []) for s in ss)
            d.text((10, y + 24), plural(len(ss), "{n} sessão", "{n} sessões") + (plural(act, " · {n} ativa", " · {n} ativas") if act else ""),
                   font=F(10, False), fill=GREEN if act else DIM)
            if ags and rh >= 52:
                d.text((10, y + 38), plural(ags, "{n} agente", "{n} agentes"), font=F(10, False), fill=PURP)
        else:
            d.text((10, y + 24), T("offline") + (T(" · visto há {dur}", dur=fmt_ago(m["seen"])) if m.get("seen") else ""),
                   font=F(10, False), fill=RED if not m.get("seen") else DIM)
            if m.get("seen") and rh >= 52:
                d.text((10, y + 38), T("às {t}", t=datetime.fromtimestamp(m["seen"]).strftime("%m/%d %H:%M" if is_en() else "%d/%m %H:%M")), font=F(10, False), fill=FAINT)
        # Byorzins das sessões
        fs = max(20, min(84, rh - 30))
        slot = fs + 14
        x0 = lw + 6
        k = max(1, (W - x0 - 6) // slot)
        if not ss:
            d.text((x0, y + rh // 2 - 8), T("nenhuma sessão") if on else T("sem sessões no último contato"),
                   font=F(11, False), fill=FAINT)
        vis = ss if len(ss) <= k else ss[:k - 1]
        for j, s in enumerate(vis):
            cx = x0 + j * slot + slot // 2
            cy = y + 4 + fs // 2
            if on:
                paste(im, face(s, fs, t, i * 7 + j), cx, cy)
                d.ellipse([cx + fs // 2 - 9, cy + fs // 2 - 9, cx + fs // 2 - 2, cy + fs // 2 - 2], fill=status_col(s))
                subs = len(s.get("subagents") or [])
                if subs:
                    lab = f"×{subs}"
                    tw = d.textlength(lab, font=F(9))
                    d.rounded_rectangle([cx + fs // 2 - tw - 2, y + 2, cx + fs // 2 + 4, y + 14], radius=6, fill=PURP)
                    d.text((cx + fs // 2 - tw + 1, y + 2), lab, font=F(9), fill=BG)
                if s["status"] == "waiting" and (t % 1) < 0.6:
                    d.text((cx - fs // 2 - 2, y + 1), "!", font=F(13), fill=YEL)
            else:
                paste(im, _offline_face(fs, m["name"]), cx, cy)
            ctext(d, cx, y + fs + 6, fit(d, name(s), F(9, False), slot - 4), F(9, False), TXT if on else FAINT)
        if len(ss) > k:
            cx = x0 + (k - 1) * slot + slot // 2
            ctext(d, cx, y + fs // 2 - 4, f"+{len(ss) - k + 1}", F(14), DIM)
    if len(ms) > 4:
        y = TOP + 3 * rh
        rest = ms[3:]
        up = sum(1 for m in rest if m["online"])
        n = sum(len(m["sessions"]) for m in rest if m["online"])
        d.text((10, y + 12), T("+{n} máquinas · {up} online", n=len(rest), up=up) + " · " +
               plural(n, "{n} sessão", "{n} sessões"), font=F(13), fill=DIM)
        d.text((10, y + 32), fit(d, ", ".join(m["name"] for m in rest), F(10, False), W - 20), font=F(10, False), fill=FAINT)
    return im


LAYOUTS = {"cards": layout_cards, "lista": layout_lista, "foco": layout_foco, "equipe": layout_equipe,
           "grade": layout_grade, "palco": layout_palco, "atividade": layout_atividade, "dashboard": layout_dashboard,
           "maquinas": layout_maquinas}
