# display: roda só com a tela plugada (udev → systemd). Busca /state no coletor local e nos
# peers, decide o modo (trabalho / acordado / sonolento / dormindo / sonhando...) e desenha.
# O comportamento vem de display.json (editável pelo painel web) e é relido sem reiniciar.
import argparse
import json
import random
import signal
import sys
import threading
import time
import urllib.request
from datetime import datetime

from byorzin_monitor.display import scenes as S
from byorzin_monitor import i18n
from byorzin_monitor.i18n import T, day_month
from byorzin_monitor.common import STATE_DIR, load_config
from byorzin_monitor.settings import Settings

FRAME_FILE = STATE_DIR / "frame.png"     # o painel mostra "o que está na tela agora"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


def _unskew(st, off):
    """Traz os horários locais do coletor para o relógio desta máquina (relógios fora de sincronia).
    resets_at vem da Anthropic (horário absoluto), então não mexe."""
    if abs(off) < 5:
        return
    for s in st.get("sessions", []):
        for k in ("since", "last"):
            if s.get(k):
                s[k] += off
    for e in st.get("events_recent", []) + st.get("alerts", []):
        if e.get("ts"):
            e["ts"] += off
    if st.get("last_activity"):
        st["last_activity"] += off
    if (st.get("rate") or {}).get("seen_at"):
        st["rate"]["seen_at"] += off
    for r in (st.get("rates") or {}).values() if isinstance(st.get("rates"), dict) else ():
        if isinstance(r, dict) and isinstance(r.get("seen_at"), (int, float)):
            r["seen_at"] += off
    st["ts"] += off


def _best(rates, k):
    """Janela mais recente (maior resets_at); dentro dela, o maior uso."""
    ws = [r[k] for r in rates if isinstance(r.get(k), dict)]
    if not ws:
        return {}
    return max(ws, key=lambda w: (w.get("resets_at") or 0, w.get("pct") or 0))


def _windows(rates):
    sd, fh = _best(rates, "seven_day"), _best(rates, "five_hour")
    return {"week_pct": sd.get("pct"), "week_resets": sd.get("resets_at"),
            "five_hour": fh.get("pct"), "five_resets": fh.get("resets_at")}


def account_tags(labels):
    """Marcador curto e único de cada conta (barra de cima e sessões): 1ª letra, 2 letras ou número."""
    out = []
    firsts = [(lab or "?")[:1].upper() for lab in labels]
    twos = [(lab or "?")[:2].capitalize() for lab in labels]
    for i, lab in enumerate(labels):
        if firsts.count(firsts[i]) == 1:
            out.append(firsts[i])
        elif twos.count(twos[i]) == 1:
            out.append(twos[i])
        else:
            out.append(str(i + 1))
    return out


def _accounts(alive, overrides, now):
    """Limites agrupados por conta. Cada coletor novo manda `rates` {conta: snapshot} e `account`
    (a conta da máquina); o mesmo snapshot de várias máquinas da mesma conta é mesclado (_best).
    Coletor antigo manda só `rate`, sem conta: entra na única conta conhecida (ou na de mesma
    janela, se houver várias); sem nenhuma conta conhecida, tudo vira uma conta sem id, como antes."""
    from byorzin_monitor.account import clean_label, valid_id
    known, legacy = {}, []
    for st in alive:
        me = st.get("account") if isinstance(st.get("account"), dict) else {}
        rs = st.get("rates")
        if isinstance(rs, dict):
            for aid, r in rs.items():
                if not valid_id(aid) or not isinstance(r, dict):
                    continue
                e = known.setdefault(aid, {"id": aid, "rates": [], "label": None, "hosts": []})
                e["rates"].append(r)
                lab = clean_label(me.get("label")) if me.get("id") == aid else None
                e["label"] = lab or e["label"] or clean_label(r.get("label"))
        elif isinstance(st.get("rate"), dict):
            legacy.append(st)
        if valid_id(me.get("id")) and me["id"] in known:
            known[me["id"]]["hosts"].append(st["host"])
    for st in legacy:
        r = st["rate"]
        if len(known) == 1:
            next(iter(known.values()))["rates"].append(r)
            continue
        ra = [(r.get(k) or {}).get("resets_at") for k in ("seven_day", "five_hour")]
        match = [e for e in known.values() if any(x and any((q.get(k) or {}).get("resets_at") == x
                 for q in e["rates"] for k in ("seven_day", "five_hour")) for x in ra)]
        if match:
            match[0]["rates"].append(r)
        else:          # sem conta conhecida (todos antigos) ou outra conta: bucket pelo nome da máquina
            key = "" if not known else "host:" + st["host"]
            e = known.setdefault(key, {"id": key, "rates": [], "label": None if not known else st["host"],
                                       "hosts": [st["host"]]})
            e["rates"].append(r)
    out = []
    for aid, e in known.items():
        lab = clean_label(overrides.get(aid)) or e["label"] or (f"conta-{aid[:4]}" if valid_id(aid) else None)
        seen = max((r.get("seen_at", now) for r in e["rates"]), default=now)
        out.append({"id": aid, "label": lab, "hosts": e["hosts"], "rates": e["rates"],
                    "rate_age": now - seen, **_windows(e["rates"])})
    out.sort(key=lambda a: ((a["label"] or "").lower(), a["id"]))
    for a, tag in zip(out, account_tags([a["label"] for a in out])):
        a["tag"] = tag
    return out


def _machines(sources, sessions, use_title):
    """Uma entrada por computador (layout "maquinas"). Offline: sessões do último contato,
    marcadas como tal — não entram em v.sessions, então não aparecem como ativas no resto."""
    out = []
    for name, st in sources:
        off = not st or bool(st.get("_offline"))
        if off:
            ss = []
            for s in (st or {}).get("sessions") or []:
                title = s.get("title") if use_title and S.clean(s.get("title") or "") else None
                ss.append({**s, "host": name, "label": title or s.get("project") or "?",
                           "status": "offline", "subagents": [], "mood": None, "tool": None})
        else:
            ss = [s for s in sessions if s["host"] == st["host"]]
        out.append({"name": name, "online": not off, "seen": (st or {}).get("_seen"), "sessions": ss,
                    "metrics": (st or {}).get("host_metrics") or {}})
    return out


class View:
    """Visão consolidada de todos os coletores (local + peers), já filtrada pelas configurações."""

    def __init__(self, sources, settings=None):
        cfg = settings or {}
        now = time.time()
        hidden = set(cfg.get("hosts_hidden") or [])
        sources = [(n, st) for n, st in sources if n not in hidden]
        # máquina offline chega com o último estado conhecido marcado "_offline" (ver Fetcher)
        self.hosts = [(name, bool(st) and not st.get("_offline")) for name, st in sources]
        self.host_seen = {name: st.get("_seen") for name, st in sources if st and st.get("_offline")}
        alive = [st for _, st in sources if st and not st.get("_offline")]
        hide_idle = (cfg.get("hide_idle_hours") or 0) * 3600
        use_title = cfg.get("session_name", "título") == "título"
        self.sessions = []
        self.hidden_idle = 0
        labels = {}
        for st in alive:
            for s in st.get("sessions", []):
                # o desenho tira o que a fonte não tem (emoji, ver scenes.clean); título só de emoji
                # ficaria vazio na tela, então vale o projeto
                title = s.get("title") if use_title and S.clean(s.get("title") or "") else None
                proj = s.get("project") or "?"
                s["label"] = title or proj           # nome principal na tela
                s["sublabel"] = proj if title else ""
                labels[s["id"]] = s["label"]
                last = max(s.get("last") or 0, s.get("since") or 0)
                if hide_idle and s.get("status") == "idle" and now - last > hide_idle:
                    self.hidden_idle += 1
                    continue
                self.sessions.append({**s, "host": st["host"]})
        # quem precisa de atenção primeiro; depois quem está trabalhando; depois o mais recente
        prio = {"waiting": 0, "limit": 0, "error": 1, "working": 1}
        self.sessions.sort(key=lambda s: (prio.get(s["status"], 2), -max(s.get("last") or 0, s["since"])))
        # limites por conta; com uma conta (o normal) tudo fica como sempre foi: uma barra só
        self.accounts = _accounts(alive, cfg.get("account_labels") or {}, now)
        self.multi_account = len(self.accounts) >= 2
        rates = [r for a in self.accounts for r in a["rates"]]
        self.rate_age = now - max((r.get("seen_at", now) for r in rates), default=now)
        if self.multi_account:
            # números gerais = a conta mais apertada (alerta, gordura do Byorzin, painel)
            wk = max(self.accounts, key=lambda a: (a["week_pct"] is not None, a["week_pct"] or 0))
            fh = max(self.accounts, key=lambda a: (a["five_hour"] is not None, a["five_hour"] or 0))
            self.week_pct, self.week_resets = wk["week_pct"], wk["week_resets"]
            self.five_hour, self.five_resets = fh["five_hour"], fh["five_resets"]
        else:
            w = self.accounts[0] if self.accounts else _windows([])
            self.week_pct, self.week_resets = w["week_pct"], w["week_resets"]
            self.five_hour, self.five_resets = w["five_hour"], w["five_resets"]
        self.limit_account = max(self.accounts, key=lambda a: max(a["five_hour"] or 0, a["week_pct"] or 0)) \
            if self.accounts else None
        self.host_account = {}
        if self.multi_account:
            by_id = {a["id"]: a for a in self.accounts}
            for st in alive:
                me = st.get("account") if isinstance(st.get("account"), dict) else {}
                if me.get("id") in by_id:
                    self.host_account[st["host"]] = by_id[me["id"]]
            for s in self.sessions:
                a = by_id.get(s.get("account")) or (self.host_account.get(s["host"]) if s.get("kind") != "llm" else None)
                if a:
                    s["account_tag"], s["account_label"] = a["tag"], a["label"]
        self.week_start = (self.week_resets - 7 * 86400) if self.week_resets else \
            max((st.get("week_start", 0) for st in alive), default=now)
        self.tok_today = sum(st.get("tokens", {}).get("today", 0) for st in alive)
        self.tok_week = sum(st.get("tokens", {}).get("week", 0) for st in alive)
        self.hourly = [sum(x) for x in zip(*[st.get("tokens", {}).get("hourly") or [0] * 24 for st in alive])] or [0] * 24
        self.events = sorted(({**e, "host": st["host"], "label": labels.get(e.get("session_id")) or e.get("project")}
                              for st in alive for e in st.get("events_recent", [])),
                             key=lambda e: e.get("ts", 0), reverse=True)
        self.last_activity = max((st.get("last_activity", 0) for st in alive), default=0)
        self.idle_for = now - self.last_activity if self.last_activity else 10 ** 9
        src = cfg.get("fat_source", "semana")
        p = self.week_pct if src == "semana" else self.five_hour if src == "5h" else None
        self.fat = (p / 100) if p is not None else 0.25
        self.metrics = [(st["host"], st["host_metrics"]) for st in alive if st.get("host_metrics")]
        self.alive = alive
        self.dream = None
        self.machines = _machines(sources, self.sessions, use_title)

    def ritmo(self):
        p, now = self.week_pct, time.time()
        if p is None or not self.week_resets:
            return None
        elapsed = now - self.week_start
        if p < 3 or elapsed < 3 * 3600:
            return (T("ritmo: ok"), "", True)
        proj = p * 7 * 86400 / elapsed
        if proj <= 100:
            return (T("ritmo: ok"), T("~{p}% no fim", p=f"{proj:.0f}"), True)
        end = self.week_start + elapsed * 100 / p
        return (T("acaba ~{when}h", when=S.fmt_when(end)[:-3]), "", False)

    def dreams(self):
        """Estatísticas para os sonhos: (número grande, linha 1, linha 2)."""
        out = []
        recs = [st.get("tokens", {}).get("record_day") for st in self.alive]
        recs = [r for r in recs if r]
        if recs:
            r = max(recs, key=lambda r: r["tokens"])
            out.append((S.fmt_tok(r["tokens"]), T("tokens em {dm}", dm=day_month(r["date"])), T("recorde do dia!")))
        for st in self.alive:
            sm = (st.get("stats") or {}).get("record_messages")
            if sm and sm.get("messages"):
                msgs = f"{sm['messages']:,}"
                out.append((msgs if i18n.is_en() else msgs.replace(",", "."), T("mensagens em {dm}", dm=day_month(sm["date"])),
                            T("{n} ferramentas", n=sm.get("tools") or 0)))
            da = (st.get("stats") or {}).get("days_active")
            if da:
                out.append((str(da), T("dias usando o Claude"), T("em {host}", host=st["host"])))
        bm = {}
        for st in self.alive:
            for k, val in (st.get("tokens", {}).get("by_model") or {}).items():
                bm[k] = bm.get(k, 0) + val
        if bm:
            k = max(bm, key=bm.get)
            out.append((k.split("-")[0].capitalize(), T("modelo favorito"), T("{x} na semana", x=S.fmt_tok(bm[k]))))
        if self.tok_week:
            out.append((S.fmt_tok(self.tok_week), T("tokens nesta semana"), T("hoje {x}", x=S.fmt_tok(self.tok_today))))
        return out


OFFLINE_AFTER = 30      # sem resposta por mais que isso = offline (com o último estado conhecido)


class Fetcher(threading.Thread):
    def __init__(self, cfg, live=None):
        super().__init__(daemon=True)
        self.token = cfg.get("token", "")
        self.urls = [f"http://127.0.0.1:{cfg['port']}"] + [u.rstrip("/") for u in cfg.get("peers", [])]
        self.names = {}
        self.last_ok = {}
        self.sources = []
        self.lock = threading.Lock()
        # [máquinas] peers/token relidos do config.toml; último estado de cada máquina vem do disco
        from byorzin_monitor.network import LiveConfig, load_seen
        self.live = live if live is not None else LiveConfig()
        for u, x in load_seen().items():
            if isinstance(x, dict) and isinstance(x.get("state"), dict) and x.get("seen"):
                self.last_ok[u] = (x["seen"], x["state"])
                self.names[u] = x.get("name") or x["state"].get("host") or u
        self._saved = 0
        self._online = {}

    def _refresh(self):
        cfg = self.live.changed()
        if cfg:
            self.token = cfg.get("token", "")
            self.urls = [f"http://127.0.0.1:{cfg['port']}"] + [u.rstrip("/") for u in cfg.get("peers", [])]

    def _persist(self, online):
        from byorzin_monitor.network import save_seen
        now = time.time()
        if online != self._online or now - self._saved > 60:
            self._online, self._saved = online, now
            save_seen({u: self.last_ok[u] for u in self.urls if u in self.last_ok}, self.names)

    def _get(self, url):
        req = urllib.request.Request(url + "/state", headers={"Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(req, timeout=1.5) as r:
            return json.load(r)

    def poll_once(self):
        """Uma rodada: busca todos os coletores e monta self.sources [(nome exibido, estado)]."""
        self._refresh()
        polled, online = [], {}
        for u in self.urls:
            try:
                st = self._get(u)
                _unskew(st, time.time() - (st.get("served_at") or st.get("ts") or time.time()))
                self.last_ok[u] = (time.time(), st)
            except Exception:
                # queda curta (reinício do coletor, wifi): segura o último estado por 30 s;
                # depois disso a máquina fica offline, mas com o último estado e "visto há"
                t, st = self.last_ok.get(u, (0, None))
                if st is not None and time.time() - t > OFFLINE_AFTER:
                    st = {**st, "_offline": True, "_seen": t}
            online[u] = bool(st) and not st.get("_offline")
            polled.append((u, st))
        out = []
        for u, name, st in dedup_sources(polled):
            self.names[u] = name
            out.append((name, st))
        with self.lock:
            self.sources = out
        self._persist(online)

    def run(self):
        while True:
            try:
                self.poll_once()
            except Exception as e:
                log("erro buscando os coletores:", repr(e))
            time.sleep(2)

    def view(self, settings=None):
        with self.lock:
            return View(list(self.sources), settings)


def _url_name(u):
    return u.split("//")[-1].split(":")[0]


def dedup_sources(polled):
    """[(url, estado)] -> [(url, nome exibido, estado)], uma entrada por instalação.
    A mesma instalação alcançada por URLs diferentes (ex.: 127.0.0.1 e o IP da LAN) aparece uma vez
    só (vale a primeira URL, a local vem antes). Instalações diferentes com o mesmo hostname ganham
    nomes distintos e estáveis pela ordem das URLs: "raspberrypi", "raspberrypi (2)"...
    O estado devolvido é uma cópia com "host" = nome exibido (cores, filtros e sessões usam esse nome).
    Coletores antigos (sem install_id) são identificados pelo hostname, como antes."""
    seen, taken, out = set(), set(), []
    for u, st in polled:
        host = (st or {}).get("host") or _url_name(u)
        if not st:
            key = ("url", u)
        elif st.get("install_id"):
            key = ("id", st["install_id"])
        else:
            key = ("host", host)
        if key in seen:
            continue
        seen.add(key)
        name, n = host, 2
        while name in taken:
            name, n = f"{host} ({n})", n + 1
        taken.add(name)
        if st and st.get("host") != name:
            st = {**st, "host": name, "_hostname": st.get("host")}
        out.append((u, name, st))
    return out


def is_night(cfg):
    h = datetime.now().hour
    a, b = cfg.get("night_start", 23), cfg.get("night_end", 7)
    return h >= a or h < b if a > b else a <= h < b


class Director:
    """Decide qual cena mostrar a cada quadro."""

    def __init__(self):
        self.known = None             # ids de sessões já vistos
        self.wake_until = 0
        self.wake_session = None
        self.dream_until = 0
        self.next_dream = time.time() + 120
        self.dream = None
        self.limit_next = None        # 1º quadro: nunca começa pela cena "limite" (ver pick)
        self.limit_until = 0
        self.host_next = time.time() + 60
        self.host_until = 0
        self.host_idx = 0
        from byorzin_monitor.display.effects import AlertFX
        self.fx = AlertFX()          # moldura de "esperando você" e comemoração de "terminou"

    def layout(self, cfg, now):
        rot = cfg.get("rotate_layouts") or []
        if len(rot) >= 2:
            return rot[int(now // max(10, cfg.get("rotate_seconds", 30))) % len(rot)]
        return cfg.get("layout", "cards")

    def forced(self, v, cfg, now):
        f = cfg.get("force") or {}
        if not f.get("mode") or now > (f.get("until") or 0):
            return None
        m = f["mode"]
        if m.startswith("layout:"):
            return "work", (m[7:],)
        if m in ("awake", "sleepy", "sleep"):
            return "idle", (m,)
        if m == "dream":
            ds = v.dreams() or [("42", T("sonho de teste"), "zzz")]
            v.dream = ds[int(now / 8) % len(ds)]
            return "idle", ("dream",)
        if m == "wake":
            s = v.sessions[0] if v.sessions else {"project": T("teste"), "host": "workstation"}
            return "wake", (s,)
        if m == "limit":
            return "limit", ()
        if m == "done":
            s = v.sessions[0] if v.sessions else {"project": T("teste"), "host": "workstation"}
            if not self.fx.celebrating(now):
                self.fx.force("done", now, {"label": s.get("label") or s["project"], "host": s["host"], "worked_s": 1380})
            return "done", (self.fx.celebrating(now),)
        if m == "alert":
            if not self.fx.framing(now):
                self.fx.force("alert", now)
            return "work", (self.layout(cfg, now),)
        if m == "host" and v.metrics:
            return "host", v.metrics[int(now / 10) % len(v.metrics)]
        return None

    def pick(self, v, cfg, now):
        ids = {(s["host"], s["id"]) for s in v.sessions}
        if self.known is not None and cfg.get("wake_animation", True):
            new = [s for s in v.sessions if (s["host"], s["id"]) not in self.known and s.get("kind") != "llm"]
            if new:
                self.wake_session, self.wake_until = new[-1], now + 3.5
        self.known = ids if v.alive else self.known
        self.fx.update(v, cfg, now)
        f = self.forced(v, cfg, now)
        if f:
            return f
        done = self.fx.celebrating(now)
        if done:
            return "done", (done,)
        if now < self.wake_until:
            return "wake", (self.wake_session,)
        if v.sessions:
            if self.limit_next is None:
                self.limit_next = now + 60
            if max(v.five_hour or 0, v.week_pct or 0) >= cfg.get("limit_alert_pct", 90) and not cfg.get("_layout_forced"):
                if now >= self.limit_next:
                    self.limit_until, self.limit_next = now + 6, now + 60
                if now < self.limit_until:
                    return "limit", ()
            return "work", (self.layout(cfg, now),)
        night = is_night(cfg)
        if v.idle_for < cfg.get("awake_minutes", 5) * 60 and not night:
            kind = "awake"
        elif v.idle_for < cfg.get("sleep_minutes", 20) * 60 and not night:
            kind = "sleepy"
        else:
            kind = "sleep"
        if kind == "sleep":
            if night and cfg.get("night_screen_off"):
                return "off", ()
            if cfg.get("dreams", True) and now >= self.next_dream:
                ds = v.dreams()
                if ds:
                    self.dream = random.choice(ds)
                    self.dream_until = now + 40
                self.next_dream = now + cfg.get("dream_every_minutes", 4) * 60
            if now < self.dream_until:
                v.dream = self.dream
                return "idle", ("dream",)
            return "idle", ("sleep",)
        if v.metrics and cfg.get("host_panel", True):
            if now >= self.host_next:
                self.host_until, self.host_next = now + 15, now + cfg.get("host_panel_every_seconds", 90)
                self.host_idx += 1
            if now < self.host_until:
                host, m = v.metrics[self.host_idx % len(v.metrics)]
                return "host", (host, m)
        return "idle", (kind,)


def fit_to(img, size):
    """Adapta o quadro (480x320, ou 480K x 320K em alta resolução) ao tamanho da tela: gira se
    ela for retrato e escala mantendo a proporção, com bordas pretas."""
    if img.size == tuple(size):
        return img
    from PIL import Image
    w, h = size
    if h > w and img.width > img.height:
        img = img.rotate(90, expand=True)
    k = min(w / img.width, h / img.height)
    res = img.resize((max(1, int(img.width * k)), max(1, int(img.height * k))), Image.LANCZOS)
    out = Image.new("RGB", (w, h), (0, 0, 0))
    out.paste(res, ((w - res.width) // 2, (h - res.height) // 2))
    return out


def render(v, mode, args, t):
    if mode == "work":
        from byorzin_monitor.display.layouts import LAYOUTS
        return LAYOUTS.get(args[0], LAYOUTS["cards"])(v, t)
    if mode == "idle":
        return S.scene_idle(v, t, args[0])
    if mode == "wake":
        return S.scene_wake(v, t, *args)
    if mode == "limit":
        return S.scene_limit(v, t)
    if mode == "host":
        return S.scene_host(v, t, *args)
    if mode == "done":
        from byorzin_monitor.display.effects import scene_done
        return scene_done(v, t, *args)
    return S.canvas((0, 0, 0))[0]


class Renderer:
    """Produz o quadro atual (480x320): busca os estados (Fetcher), lê os ajustes, decide a cena
    (Director) e desenha. Usado pela tela USB, pelo terminal e pela página /tela do painel."""

    def __init__(self, cfg=None, settings=None, fetcher=None, layout=None):
        self.cfg = cfg if cfg is not None else load_config()
        self.settings = settings or Settings()
        if fetcher is None:
            fetcher = Fetcher(self.cfg)
            fetcher.start()
        self.fetcher = fetcher
        self.director = Director()
        self.layout = layout              # força um layout (ex.: ?layout= da página /tela)
        self.t0 = time.time()
        self.mode, self.args, self.cfg_now = None, (), {}

    def wait_ready(self, timeout=2.5):
        """Espera a primeira rodada do Fetcher (no máximo `timeout` s)."""
        end = time.time() + timeout
        while time.time() < end:
            with self.fetcher.lock:
                if self.fetcher.sources:
                    return True
            time.sleep(0.1)
        return False

    def current_settings(self):
        cfg = self.settings.get()
        if self.layout:     # layout pedido explicitamente: sem alerta de limite por cima
            cfg = {**cfg, "layout": self.layout, "rotate_layouts": [], "_layout_forced": True}
        return cfg

    def frame(self, now=None, scale=1):
        """Quadro lógico do momento; guarda modo/args/ajustes usados em self.mode/args/cfg_now.
        `scale` > 1 desenha o mesmo quadro em alta resolução (480K x 320K, ver scenes.scaled);
        a tela USB usa sempre 1."""
        now = time.time() if now is None else now
        cfg = self.current_settings()
        S.set_colors(cfg.get("colors"))
        i18n.set_lang(cfg.get("language"))
        v = self.fetcher.view(cfg)
        self.mode, self.args = self.director.pick(v, cfg, now)
        self.cfg_now = cfg
        self.now = now
        t = now - self.t0
        with S.scaled(scale):
            return self.director.fx.decorate(render(v, self.mode, self.args, t), now, t)

    def frame_for(self, size, now=None):
        return fit_to(self.frame(now), size)

    def brightness(self):
        cfg = self.cfg_now
        if self.director.fx.max_brightness(cfg, getattr(self, "now", time.time())):
            return 100                    # alerta "esperando você": brilho máximo por alguns segundos
        night = is_night(cfg) and self.mode == "idle"
        return cfg["brightness_night"] if night else cfg["brightness_day"]


def save_frame(img):
    tmp = FRAME_FILE.with_suffix(".tmp.png")
    FRAME_FILE.parent.mkdir(parents=True, exist_ok=True)
    img.save(tmp)
    tmp.replace(FRAME_FILE)


class DisplayError(RuntimeError):
    """Erro com mensagem para o usuário (sem traceback)."""


def _parse_size(v):
    try:
        w, h = (int(x) for x in v.lower().split("x"))
        if w > 0 and h > 0:
            return w, h
    except ValueError:
        pass
    raise argparse.ArgumentTypeError(f"tamanho inválido: {v} (use LARGURAxALTURA, ex.: 480x320)")


def build_parser(prog="byorzin-monitor display"):
    from byorzin_monitor.display.backends import BACKENDS, KNOWN_USB
    from byorzin_monitor.display.layouts import LAYOUTS
    usb = ", ".join(sorted({k[3] for k in KNOWN_USB}))
    epilog = (f"telas (--backend): auto (detecta a 1ª tela USB conhecida), {', '.join(BACKENDS)}, web\n"
              f"  USB: {usb}; terminal = no próprio terminal; framebuffer = /dev/fbN (ou um arquivo, para teste);\n"
              "  sim = simulador que grava PNGs; web = página /tela do painel (não roda aqui)\n"
              f"layouts (--layout): {', '.join(LAYOUTS)}\n"
              "exemplos:\n"
              "  byorzin-monitor display --png quadro.png --layout grade\n"
              "  byorzin-monitor display --backend terminal\n"
              "  byorzin-monitor display --backend framebuffer --device /tmp/fb.raw --size 480x320 --bpp 16\n"
              "mais detalhes: docs/telas.md")
    ap = argparse.ArgumentParser(prog=prog, description="Roda a tela do Byorzin (normalmente como serviço).",
                                 epilog=epilog, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", default=None, metavar="TELA",
                    help="tipo de tela (padrão: `backend` do config.toml, ou auto); lista abaixo")
    ap.add_argument("--device", "--port", default=None, metavar="DISPOSITIVO",
                    help="porta serial (/dev/ttyACM0), framebuffer (/dev/fb1) ou arquivo; padrão: detectar")
    ap.add_argument("--png", default=None, metavar="ARQUIVO",
                    help="em vez de abrir a tela, salva o quadro atual neste PNG e sai (teste)")
    ap.add_argument("--layout", default=None, metavar="LAYOUT",
                    help="fixa um layout (ignora o escolhido no painel e a rotação)")
    ap.add_argument("--size", type=_parse_size, default=None, metavar="LxA",
                    help="framebuffer em arquivo: tamanho, ex.: 480x320")
    ap.add_argument("--bpp", type=int, choices=(16, 24, 32), default=None,
                    help="framebuffer em arquivo: bits por pixel (padrão 16)")
    ap.add_argument("--wait", action="store_true",
                    help="sem tela USB plugada, espera ela aparecer em vez de sair (serviço no macOS)")
    return ap


def wait_for_screen(stop, every=3.0):
    """Espera uma tela USB conhecida aparecer (no Linux quem faz isso é o udev). Devolve False se
    pediram para parar antes."""
    from byorzin_monitor.display.backends import detect
    told = False
    while not stop:
        if detect():
            return True
        if not told:
            log("esperando uma tela USB ser plugada…")
            told = True
        time.sleep(every)
    return False


def main(argv=None):
    ap = build_parser()
    a = ap.parse_args(argv)
    conf = load_config()
    from byorzin_monitor.display.backends import BACKENDS
    from byorzin_monitor.display.layouts import LAYOUTS
    backend = a.backend or conf.get("backend", "auto") or "auto"
    if backend not in BACKENDS and backend not in ("auto", "web"):
        raise DisplayError(f"tela desconhecida: {backend}. Opções: auto, {', '.join(BACKENDS)}, web "
                           "(veja `byorzin-monitor display --help`)")
    if a.layout and a.layout not in LAYOUTS:
        raise DisplayError(f"layout desconhecido: {a.layout}. Opções: {', '.join(LAYOUTS)}")
    if backend == "web" and not a.png:
        log(f"a tela no navegador é servida pelo painel: http://<esta-máquina>:{conf['panel_port']}/tela")
        return 0
    opts = {}
    if a.size or a.bpp:
        if backend != "framebuffer":
            raise DisplayError("--size/--bpp só valem com --backend framebuffer")
        opts = {"size": a.size, "bpp": a.bpp}
    stop = []
    if a.wait and not a.png and backend == "auto" and not (a.device or conf.get("device")):
        signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
        if not wait_for_screen(stop):     # sem tela ainda: não busca dados à toa
            return 0
    renderer = Renderer(conf, layout=a.layout)
    renderer.wait_ready()
    if a.png:
        renderer.t0 = time.time()
        try:
            renderer.frame().save(a.png)
        except (OSError, ValueError) as e:
            raise DisplayError(f"não consegui salvar {a.png}: {e}") from None
        log("quadro salvo em", a.png, "modo", renderer.mode)
        return 0
    from byorzin_monitor.display.backends import open_backend
    try:
        scr = open_backend(backend, a.device or conf.get("device", ""), **opts)
    except DisplayError:
        raise
    except RuntimeError as e:
        raise DisplayError(str(e)) from None
    except FileNotFoundError as e:
        raise DisplayError(f"dispositivo não encontrado: {e.filename or e}. A tela está plugada? "
                           "Veja `byorzin-monitor doctor`.") from None
    except PermissionError as e:
        raise DisplayError(f"sem permissão para abrir {e.filename or 'a tela'}: entre no grupo "
                           "dialout (serial) ou video (framebuffer) e faça login de novo.") from None
    except Exception as e:
        if type(e).__name__ == "SerialException":
            raise DisplayError(f"não consegui abrir a porta serial: {e}") from None
        raise
    say = (lambda *_: None) if scr.quiet else log
    say(f"tela aberta: {scr.label} {scr.size[0]}x{scr.size[1]}")
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))   # termina o quadro atual antes de sair
    renderer.t0 = time.time()
    last_mode = None
    screen_on = True
    frames, pixels, stat_t, saved_t = 0, 0, time.time(), 0
    try:
        while not stop:
            now = time.time()
            img = renderer.frame(now)
            mode, args, cfg = renderer.mode, renderer.args, renderer.cfg_now
            if mode == "off":
                if screen_on:
                    scr.off()
                    screen_on = False
            else:
                if not screen_on:
                    scr.on()
                    screen_on = True
                scr.set_brightness(renderer.brightness())
            if screen_on:
                pixels += scr.show(fit_to(img, scr.size), full=False)
            frames += 1
            if scr.save_frame and now - saved_t > 2:
                save_frame(img)
                saved_t = now
            if now - stat_t > 60:
                say(f"{frames / (now - stat_t):.1f} fps, {pixels / frames / 1000:.1f}k px/quadro")
                frames, pixels, stat_t = 0, 0, now
            key = (mode,) + tuple(x for x in args if isinstance(x, str))
            if key != last_mode:
                say("modo:", *key)
                last_mode = key
            time.sleep(max(0.0, 1 / cfg.get("fps", 5) - (time.time() - now)))
        say("encerrando")
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as e:     # cabo desconectado etc.: sai e o systemd decide
        scr.close()
        log("erro na tela:", repr(e))
        return 1
    finally:
        scr.close()


if __name__ == "__main__":
    sys.exit(main())
