# panel: painel web do display (porta 8788). Escolhe layout, edita as configurações, mostra o
# que está na tela agora e testa cenas na tela real. Ao salvar, replica para os painéis dos peers,
# então a tela fica igual em qualquer máquina onde for plugada.
import io
import json
import math
import os
import re
import secrets
import sys
import threading
import time
import urllib.request
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, quote, urlencode, urlparse

from byorzin_monitor.display import scenes as S
from byorzin_monitor.common import load_config
from byorzin_monitor.display.demo import demo_view
from byorzin_monitor.display.engine import FRAME_FILE, Fetcher
from byorzin_monitor.display.layouts import LAYOUTS
from byorzin_monitor.account import LABEL_MAX, clean_label, valid_id as valid_account
from byorzin_monitor.settings import (LAYOUT_NAMES, SCHEMA, SETTINGS_FILE, Settings, account_label_ok, as_bool, save,
                                      valid_color, validate)
from byorzin_monitor import __version__, i18n
from byorzin_monitor import network as net
from byorzin_monitor import pairing
from byorzin_monitor.panel import auth

PORT = 8788
T0 = time.time()

LAYOUT_INFO = {
    "cards": ("Cards", "Uma coluna por sessão com o Byorzin grande; agentes numa fila de rostinhos embaixo."),
    "lista": ("Lista", "Uma linha por sessão: nome, título, status e os agentes com o que estão fazendo."),
    "foco": ("Foco", "A sessão mais importante em destaque (quem espera você primeiro); as outras em miniatura."),
    "equipe": ("Equipe", "Organograma: sessões no topo e seus agentes pendurados embaixo, com tipo e ferramenta."),
    "grade": ("Grade", "Mosaico compacto de até 8 sessões, com borda colorida pelo status e nº de agentes."),
    "palco": ("Palco", "Byorzins em pé num palco com balões de fala do que estão fazendo; agentes ao lado."),
    "atividade": ("Atividade", "Sessões à esquerda e o feed ao vivo dos eventos (ferramentas, agentes, permissões)."),
    "dashboard": ("Dashboard", "Números: sessões ativas, agentes, tokens de hoje, semana + gráfico de tokens por hora."),
    "maquinas": ("Máquinas", "Uma faixa por computador: online ou offline (visto há…), sessões e os Byorzins de cada um."),
}
LAYOUT_INFO_EN = {
    "cards": ("Cards", "One column per session with a big Byorzin; agents in a row of little faces below."),
    "lista": ("List", "One row per session: name, title, status and what each agent is doing."),
    "foco": ("Focus", "The most important session up front (whoever is waiting for you first); the rest as thumbnails."),
    "equipe": ("Team", "Org chart: sessions on top with their agents hanging below, with type and tool."),
    "grade": ("Grid", "Compact mosaic of up to 8 sessions, border colored by status, with the agent count."),
    "palco": ("Stage", "Byorzins standing on a stage with speech bubbles of what they are doing; agents beside them."),
    "atividade": ("Activity", "Sessions on the left and a live feed of events (tools, agents, permissions)."),
    "dashboard": ("Dashboard", "Numbers: active sessions, agents, today's tokens, week + tokens per hour chart."),
    "maquinas": ("Machines", "One strip per computer: online or offline (last seen…), sessions and their Byorzins."),
}
SCENES_EN = {"awake": "Awake", "sleepy": "Sleepy", "sleep": "Sleeping", "dream": "Dreaming",
             "wake": "Startled (new session)", "limit": "Limit alert", "host": "Host panel",
             "alert": "Waiting for you (frame)", "done": "Finished (celebration)"}
SCENES = {"awake": "Acordado", "sleepy": "Sonolento", "sleep": "Dormindo", "dream": "Sonhando",
          "wake": "Susto (nova sessão)", "limit": "Alerta de limite", "host": "Painel do host",
          "alert": "Esperando você (moldura)", "done": "Terminou (comemoração)"}

# grupos do formulário: (título, [(chave, rótulo, dica)])
FORM = [
    ("Tela", [
        ("language", "Idioma da tela", "textos desenhados na tela física e em /tela"),
    ]),
    ("Brilho e noite", [
        ("brightness_day", "Brilho de dia", ""),
        ("brightness_night", "Brilho à noite", "usado quando ocioso no horário noturno"),
        ("night_start", "Noite começa às", ""),
        ("night_end", "Noite termina às", ""),
        ("night_screen_off", "Desligar a tela à noite sem sessões", ""),
    ]),
    ("Byorzin ocioso", [
        ("awake_minutes", "Fica acordado por", "após a última atividade, antes de ficar sonolento"),
        ("sleep_minutes", "Dorme depois de", "contados desde a última atividade"),
        ("dreams", "Sonhar com estatísticas", "recordes, modelo favorito, dias de uso…"),
        ("dream_every_minutes", "Sonhar a cada", ""),
        ("host_panel", "Painel da máquina (CPU/GPU/Docker)", "alterna com o Byorzin quando ocioso"),
        ("host_panel_every_seconds", "Painel da máquina a cada", ""),
        ("wake_animation", "Susto quando abre sessão nova", ""),
    ]),
    ("Sessões e alertas", [
        ("session_name", "Nome das sessões", "título = o mesmo da aba do terminal"),
        ("hide_idle_hours", "Ocultar ociosas há mais de", "0 = mostra todas"),
        ("limit_alert_pct", "Alerta de limite a partir de", "vale para a semana e a janela de 5h"),
        ("fat_source", "Byorzin engorda com", "semana, janela de 5h ou fixo"),
    ]),
    ("Animação", [
        ("fps", "Quadros por segundo", "a tela aguenta ~5; menos = mais leve"),
    ]),
    ("Alertas e notificações", [
        ("alert_screen", "Moldura piscando quando alguém espera você", "permissão, pergunta ou sessão parada"),
        ("alert_screen_seconds", "Duração do efeito na tela", ""),
        ("alert_max_brightness", "Brilho máximo durante o alerta", ""),
        ("alert_idle", "Avisar também sessão ociosa esperando", "o Claude Code avisa ~1 min depois de terminar"),
        ("alert_cooldown_seconds", "Intervalo mínimo por sessão", "evita avisos repetidos da mesma sessão"),
        ("done_minutes", "\"Terminou\" só se trabalhou mais de", "comemora e avisa quando uma sessão longa acaba"),
        ("done_celebrate", "Comemorar na tela quando termina", ""),
        ("alert_browser", "Notificação do navegador", "permita no botão abaixo, em cada navegador"),
        ("alert_sound", "Som curto no painel", ""),
        ("ntfy_enabled", "Enviar para o celular (ntfy)", "quem envia é o coletor da máquina da sessão"),
        ("ntfy_server", "Servidor ntfy", "ex.: https://ntfy.sh ou o seu"),
        ("ntfy_topic", "Tópico ntfy", "use um nome difícil de adivinhar"),
        ("ntfy_waiting", "ntfy: esperando você", ""),
        ("ntfy_done", "ntfy: terminou", ""),
    ]),
    ("LLM local", [
        ("llm_session", "Mostrar o Ollama como sessão", "Byorzin rosa de fone enquanto um modelo gera"),
        ("llm_gpu_pct", "GPU acima de", "com modelo carregado, conta como gerando"),
        ("llm_linger_seconds", "Continua na tela por", "depois que o modelo para de gerar"),
    ]),
]

# tradução do formulário: título do grupo e (rótulo, dica) de cada ajuste
FORM_GROUPS_EN = {"Tela": "Screen", "Brilho e noite": "Brightness and night", "Byorzin ocioso": "Idle Byorzin",
                  "Sessões e alertas": "Sessions and alerts", "Animação": "Animation",
                  "Alertas e notificações": "Alerts and notifications", "LLM local": "Local LLM"}
FORM_EN = {
    "language": ("Screen language", "text drawn on the physical screen and on /tela"),
    "brightness_day": ("Daytime brightness", ""),
    "brightness_night": ("Night brightness", "used when idle during night hours"),
    "night_start": ("Night starts at", ""),
    "night_end": ("Night ends at", ""),
    "night_screen_off": ("Turn the screen off at night with no sessions", ""),
    "awake_minutes": ("Stays awake for", "after the last activity, before getting sleepy"),
    "sleep_minutes": ("Falls asleep after", "counted from the last activity"),
    "dreams": ("Dream about statistics", "records, favorite model, days of use…"),
    "dream_every_minutes": ("Dream every", ""),
    "host_panel": ("Machine panel (CPU/GPU/Docker)", "alternates with the Byorzin when idle"),
    "host_panel_every_seconds": ("Machine panel every", ""),
    "wake_animation": ("Startle when a new session opens", ""),
    "session_name": ("Session name", "title = same as the terminal tab title; project = folder name"),
    "hide_idle_hours": ("Hide sessions idle for more than", "0 = show all"),
    "limit_alert_pct": ("Limit alert from", "applies to the week and the 5h window"),
    "fat_source": ("Byorzin gets fatter with", "week, 5-hour window or fixed"),
    "fps": ("Frames per second", "the screen handles ~5; fewer = lighter"),
    "alert_screen": ("Flashing frame when someone is waiting for you", "permission, question or stalled session"),
    "alert_screen_seconds": ("Duration of the screen effect", ""),
    "alert_max_brightness": ("Maximum brightness during the alert", ""),
    "alert_idle": ("Also alert idle sessions waiting", "Claude Code notifies ~1 min after finishing"),
    "alert_cooldown_seconds": ("Minimum interval per session", "avoids repeated alerts for the same session"),
    "done_minutes": ("\"Finished\" only if it worked more than", "celebrates and notifies when a long session ends"),
    "done_celebrate": ("Celebrate on screen when it finishes", ""),
    "alert_browser": ("Browser notification", "allow it with the button below, in each browser"),
    "alert_sound": ("Short sound in the panel", ""),
    "ntfy_enabled": ("Send to your phone (ntfy)", "sent by the collector of the session's machine"),
    "ntfy_server": ("ntfy server", "e.g. https://ntfy.sh or your own"),
    "ntfy_topic": ("ntfy topic", "use a name that is hard to guess"),
    "ntfy_waiting": ("ntfy: waiting for you", ""),
    "ntfy_done": ("ntfy: finished", ""),
    "llm_session": ("Show Ollama as a session", "pink Byorzin with headphones while a model generates"),
    "llm_gpu_pct": ("GPU above", "with a model loaded, counts as generating"),
    "llm_linger_seconds": ("Stays on screen for", "after the model stops generating"),
}
FORM_EN_LIST = [(FORM_GROUPS_EN.get(g, g), [(k, *FORM_EN.get(k, (lab, hint))) for k, lab, hint in fs]) for g, fs in FORM]


def default_colors(names):
    return {n: S.default_color(n) for n in names}


class Panel:
    def __init__(self):
        self.live = net.LiveConfig()          # token/peers relidos sem reiniciar (pareamento)
        self.settings = Settings()
        self.fetcher = Fetcher(self.cfg)
        self.fetcher.start()
        self.lock = threading.Lock()          # desenho (as cenas usam estado global)
        self.slock = threading.Lock()         # leitura-alteração-gravação do display.json
        self.pairing = pairing.Pairing()
        self.mid = net.install_id()
        on, dport, daddr = net.disc_params(self.cfg)
        self.listener = net.Listener(dport, daddr, own_id=self.mid)
        if on:
            self.listener.start()

    @property
    def cfg(self):
        return self.live.get()

    @property
    def auth_mode(self):
        return "off" if str(self.cfg.get("panel_auth", "lan")).lower() == "off" else "lan"

    def peer_urls(self):
        return [net.norm_url(u) for u in self.cfg.get("peers", [])]

    @property
    def peers(self):
        """Painéis dos peers (para replicar display.json)."""
        return [net.panel_of(u, self.cfg) for u in self.cfg.get("peers", [])]

    def current(self):
        return dict(self.settings.get())

    def _saved(self, new):
        # o cache do Settings é por mtime, que pode não mudar em gravações seguidas: guarda o que gravou
        self.settings.data = new
        try:
            self.settings._mtime = os.stat(SETTINGS_FILE).st_mtime
        except OSError:
            pass

    def update(self, patch, sync=True):
        with self.slock:
            cur = self.current()
            cur.update(patch)
            cur["updated_at"] = time.time()
            cur["rev"] = int(cur.get("rev") or 0) + 1
            new = save(cur)
            self._saved(new)
        if sync:
            threading.Thread(target=self._sync, args=(new,), daemon=True).start()
        return new

    def apply_remote(self, data):
        """Ajustes vindos de um peer: vence o maior rev; empate, o updated_at mais novo."""
        with self.slock:
            cur = self.current()
            new = validate(data)
            mine = (int(cur.get("rev") or 0), float(cur.get("updated_at") or 0))
            theirs = (new["rev"], new["updated_at"])
            if theirs <= mine:
                return False
            self._saved(save(new))
            return True

    def _sync(self, data):
        body = json.dumps(data).encode()
        tok = self.cfg.get("token")
        if not tok:
            return
        for p in self.peers:
            try:
                req = urllib.request.Request(p + "/api/sync", data=body, method="POST",
                                             headers={"Authorization": f"Bearer {tok}",
                                                      "Content-Type": "application/json", auth.CSRF_HEADER: "1"})
                urllib.request.urlopen(req, timeout=3).read()
            except Exception as e:
                print("sync falhou para", p, repr(e), file=sys.stderr, flush=True)

    def frame_local(self):
        try:
            if time.time() - FRAME_FILE.stat().st_mtime < 10:
                return FRAME_FILE.read_bytes()
        except OSError:
            pass
        return None

    def frame_any(self):
        """(png, nome da máquina) da tela física, aqui ou num peer; (None, None) se não há tela."""
        b = self.frame_local()
        if b:
            return b, self.cfg["hostname"]
        cfg = self.cfg
        tok = cfg.get("token")
        meta = net.machines_meta()
        for u in self.peer_urls():
            p = net.panel_of(u, cfg)
            try:
                req = urllib.request.Request(p + "/img/now-local.png",
                                             headers={"Authorization": f"Bearer {tok}"} if tok else {})
                with urllib.request.urlopen(req, timeout=2) as r:
                    name = self.fetcher.names.get(u) or meta.get(u, {}).get("host") or net.url_host(u)
                    return r.read(), name
            except Exception:
                continue
        return None, None

    def render(self, kind, name, data):
        cfg = self.current()
        S.set_colors(cfg.get("colors"))
        i18n.set_lang(cfg.get("language"))
        v = demo_view(cfg) if data == "demo" else demo_view(cfg, multi_account=True) if data == "demo2" \
            else self.fetcher.view(cfg)
        t = time.time() - T0
        if kind == "layout":
            if not v.sessions:
                return S.scene_idle(v, t, "awake")
            return LAYOUTS[name](v, t)
        if name in ("awake", "sleepy", "sleep"):
            return S.scene_idle(v, t, name)
        if name == "dream":
            ds = v.dreams() or [("42", i18n.T("sonho de teste"), "zzz")]
            v.dream = ds[int(t / 5) % len(ds)]
            return S.scene_idle(v, t, "dream")
        if name == "wake":
            s = v.sessions[0] if v.sessions else {"project": i18n.T("teste"), "host": self.cfg["hostname"]}
            return S.scene_wake(v, t, s)
        if name == "limit":
            return S.scene_limit(v, t)
        if name == "done":
            from byorzin_monitor.display.effects import scene_done
            s = v.sessions[0] if v.sessions else {"project": i18n.T("teste"), "host": self.cfg["hostname"]}
            return scene_done(v, t, {"label": s.get("label") or s["project"], "host": s["host"], "worked_s": 1380})
        if name == "alert":
            from byorzin_monitor.display.effects import alert_frame
            base = LAYOUTS.get(cfg.get("layout"), LAYOUTS["cards"])(v, t) if v.sessions else S.scene_idle(v, t, "awake")
            return alert_frame(base, t)
        if name == "host":
            if v.metrics:
                return S.scene_host(v, t, *v.metrics[int(t / 6) % len(v.metrics)])
            return S.scene_idle(v, t, "awake")
        return None

    def machines(self):
        with self.fetcher.lock:
            srcs = list(self.fetcher.sources)
            url_of = {n: u for u, n in self.fetcher.names.items() if u in self.fetcher.urls}
            local_url = self.fetcher.urls[0]
        meta = net.machines_meta()
        out, ids = [], set()
        for name, st in srcs:
            iid = (st or {}).get("install_id")
            if iid:                              # a mesma instalação por dois endereços: mostra uma vez
                if iid in ids:
                    continue
                ids.add(iid)
            u = url_of.get(name, "")
            local = u == local_url
            m = {"name": name, "up": bool(st) and not st.get("_offline"), "local": local,
                 "url": "" if local else u, "seen": (st or {}).get("_seen"),
                 "id": iid or meta.get(u, {}).get("id", ""),
                 "panel": net.panel_of(u, self.cfg) if u and not local else "",
                 "account": self._machine_account(st)}
            if st:
                ss = st.get("sessions", [])
                hm = st.get("host_metrics") or {}
                m.update(sessions=len(ss), active=sum(1 for x in ss if x.get("status") in ("working", "waiting")),
                         agents=sum(len(x.get("subagents") or []) for x in ss),
                         tok_today=st.get("tokens", {}).get("today", 0), cpu=hm.get("cpu"),
                         ram=f"{hm.get('ram_used_gb', 0):.0f}/{hm.get('ram_total_gb', 0):.0f} GB" if hm.get("ram_total_gb") else None,
                         gpu=(hm.get("gpu") or {}).get("util"), ollama=[o.get("name") for o in hm.get("ollama") or []])
            out.append(m)
        return out

    # --- várias contas (ver docs/maquinas.md, "Várias contas")
    def _machine_account(self, st):
        """{id, label} da conta da máquina (rótulo do painel, se houver); None em coletor antigo."""
        me = (st or {}).get("account")
        if not isinstance(me, dict) or not valid_account(me.get("id")):
            return None
        labels = self.current().get("account_labels") or {}
        return {"id": me["id"], "label": clean_label(labels.get(me["id"])) or clean_label(me.get("label")) or me["id"]}

    def accounts(self, v=None):
        """Contas vistas em todas as máquinas: as com limites (status line) e as sem (API key ou
        sem resposta ainda). Só id derivado e rótulo, nunca e-mail ou uuid."""
        cfg = self.current()
        labels = cfg.get("account_labels") or {}
        v = v or self.fetcher.view(cfg)
        with self.fetcher.lock:
            srcs = list(self.fetcher.sources)
        orig = {}
        for _, st in srcs:
            me = (st or {}).get("account")
            if isinstance(me, dict) and valid_account(me.get("id")) and clean_label(me.get("label")):
                orig.setdefault(me["id"], clean_label(me["label"]))
            for aid, r in ((st or {}).get("rates") or {}).items() if isinstance((st or {}).get("rates"), dict) else ():
                if valid_account(aid) and isinstance(r, dict) and clean_label(r.get("label")):
                    orig.setdefault(aid, clean_label(r["label"]))
        out = {}
        for a in v.accounts:
            if not valid_account(a["id"]):
                continue           # coletores antigos sem conta: não dá para renomear
            out[a["id"]] = {"id": a["id"], "label": a["label"], "limits": True, "hosts": list(a["hosts"]),
                            "week": a["week_pct"], "five": a["five_hour"],
                            "week_resets": a["week_resets"], "five_resets": a["five_resets"]}
        for name, st in srcs:
            me = (st or {}).get("account")
            if not isinstance(me, dict) or not valid_account(me.get("id")):
                continue
            e = out.setdefault(me["id"], {"id": me["id"], "label": None, "limits": False, "hosts": [],
                                          "week": None, "five": None, "week_resets": None, "five_resets": None})
            if name not in e["hosts"]:
                e["hosts"].append(name)
        for aid, e in out.items():
            e["default"] = "API key" if aid == "api" else orig.get(aid) or f"conta-{aid[:4]}"
            e["label"] = clean_label(labels.get(aid)) or e["label"] or e["default"]
            e["custom"] = aid in labels
        return sorted(out.values(), key=lambda e: (e["label"].lower(), e["id"]))

    def found(self):
        """Máquinas anunciando na rede que ainda não estão pareadas com esta."""
        cfg, meta = self.cfg, net.machines_meta()
        return [m for m in self.listener.items() if not net.is_paired(m, cfg, meta)]

    def net_state(self):
        on, dport, _ = net.disc_params(self.cfg)
        return {"found": self.found(), "pairing": self.pairing.status(), "id": self.mid,
                "discovery": {"on": on, "port": dport, "listening": self.listener.ok},
                "token_set": bool(self.cfg.get("token"))}

    def allowed_legacy(self, handler):
        """Só com panel_auth = "off": regra antiga (desta máquina, de um peer pelo IP ou pair_from_anywhere)."""
        ip = handler.client_address[0]
        # loopback só vale com Host local: senão um site qualquer (DNS rebinding) passaria por aqui
        if auth.is_local(ip, handler.headers.get("Host"), handler.connection.getsockname()[0]):
            return True
        if self.cfg.get("pair_from_anywhere"):
            return True
        return ip in {net.url_host(u) for u in self.cfg.get("peers", [])}

    def summary(self, v=None):
        v = v or self.fetcher.view(self.current())
        return {"sessions": len(v.sessions), "hidden": v.hidden_idle,
                "active": sum(1 for s in v.sessions if s["status"] in ("working", "waiting")),
                "waiting": sum(1 for s in v.sessions if s["status"] == "waiting"),
                "agents": sum(len(s.get("subagents") or []) for s in v.sessions),
                "week": v.week_pct, "five": v.five_hour, "week_resets": v.week_resets,
                "tok_today": S.fmt_tok(v.tok_today), "tok_week": S.fmt_tok(v.tok_week),
                # limites por conta: só aparece separado com 2+ contas (com uma, igual a week/five)
                "accounts": [{"id": a["id"], "label": a["label"], "week": a["week_pct"], "five": a["five_hour"],
                              "week_resets": a["week_resets"], "five_resets": a["five_resets"]}
                             for a in v.accounts] if v.multi_account else [],
                "list": [{"label": s["label"], "sub": s.get("sublabel"), "host": s["host"], "status": s["status"],
                          "id": s["id"], "kind": s.get("kind"),
                          "tool": S.tool_name(s.get("tool"), 24) or None, "agents": len(s.get("subagents") or []),
                          "ctx": s.get("context_pct"), "account": s.get("account") if valid_account(s.get("account")) else None}
                         for s in v.sessions[:12]]}

    def state(self, secrets_ok=True, local=False):
        with self.fetcher.lock:
            hosts = [(n, st is not None) for n, st in self.fetcher.sources]
        v = self.fetcher.view(self.current())
        schema = {k: {"default": d, "type": typ, "min": lo if typ == "int" else None, "max": hi,
                      "choices": lo if typ in ("choice",) else None} for k, (d, typ, lo, hi) in SCHEMA.items()}
        return {"machine": self.cfg["hostname"], "version": __version__, "screen_here": self.frame_local() is not None,
                "hosts": hosts, "settings": public_settings(self.current(), secrets_ok),
                "schema": schema, "form": FORM, "form_en": FORM_EN_LIST,
                "layouts": [{"id": k, "name": LAYOUT_INFO[k][0], "desc": LAYOUT_INFO[k][1],
                             "name_en": LAYOUT_INFO_EN[k][0], "desc_en": LAYOUT_INFO_EN[k][1]} for k in LAYOUT_NAMES],
                "scenes": SCENES, "scenes_en": SCENES_EN, "peers": self.peers, "machines": self.machines(), "summary": self.summary(v),
                "accounts": self.accounts(v),
                "alerts": self.alerts(),
                "net": self.net_state(),
                "access": {"local": local, "auth": self.auth_mode},
                "default_colors": default_colors({n for n, _ in hosts} | {self.cfg["hostname"]}),
                "palette": S.PALETTE}

    # --- recursos: alertas, histórico e detalhe da sessão (ver docs/recursos.md)
    def alerts(self):
        with self.fetcher.lock:
            srcs = list(self.fetcher.sources)
        out = [{**a, "host": a.get("host") or name} for name, st in srcs if st for a in st.get("alerts") or []]
        return sorted(out, key=lambda a: a.get("ts", 0))[-30:]

    def _collector_get(self, url, path, timeout=3, with_meta=False):
        req = urllib.request.Request(url + path, headers={"Authorization": f"Bearer {self.cfg.get('token', '')}"})
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
            date = r.headers.get("Date")
        if with_meta:
            return d, (t0 + time.time()) / 2, date
        return d

    def _url_of(self, host):
        with self.fetcher.lock:
            for u, n in self.fetcher.names.items():
                if n == host:
                    return u
        return None

    def session(self, host, sid):
        u = self._url_of(host)
        if not u:
            return None
        try:
            d, mid, date = self._collector_get(u, "/session?id=" + quote(sid, safe=""), with_meta=True)
        except Exception:
            return None
        if not isinstance(d, dict) or not isinstance(d.get("session"), dict):
            return None
        unskew_session(d, clock_offset(d, mid, date))
        d["_now"] = time.time()
        return d

    def history(self, ndays):
        """Junta o GET /history de todas as máquinas e soma por dia, modelo, ferramenta e agente."""
        ndays = max(1, min(90, ndays))
        per, errors, seen = {}, [], set()
        for u in self.fetcher.urls:
            try:
                h = self._collector_get(u, f"/history?days={ndays}", timeout=4)
            except Exception:
                errors.append(self.fetcher.names.get(u, u.split("//")[-1].split(":")[0]))
                continue
            key = h.get("install_id") or h.get("host")
            if key in seen:      # peer apontando para a própria máquina
                continue
            seen.add(key)
            name = self.fetcher.names.get(u) or h.get("host") or u     # mesmo nome exibido no resto do painel
            if name in per:      # duas instalações com o mesmo nome: não soma uma por cima da outra
                name = f"{name} ({u.split('//')[-1]})"
            per[name] = h.get("days") or {}
        today = datetime.now()
        dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(ndays - 1, -1, -1)]
        out = {"days": ndays, "dates": dates, "hosts": sorted(per), "errors": errors,
               "tokens": {}, "sessions": [0] * ndays, "work_s": [0] * ndays, "prompts": [0] * ndays,
               "models": {}, "tools": {}, "agents": {}, "by_host": {}}
        for host, days in per.items():
            out["tokens"][host] = [0] * ndays
            bh = out["by_host"][host] = {"tokens": 0, "sessions": 0, "work_s": 0, "agents": 0}
            for i, dt in enumerate(dates):
                d = days.get(dt)
                if not d:
                    continue
                out["tokens"][host][i] = d.get("tokens", 0)
                out["sessions"][i] += d.get("sessions", 0)
                out["work_s"][i] += d.get("work_s", 0)
                out["prompts"][i] += d.get("prompts", 0)
                bh["tokens"] += d.get("tokens", 0)
                bh["sessions"] += d.get("sessions", 0)
                bh["work_s"] += d.get("work_s", 0)
                for key in ("models", "tools", "agents"):
                    for k, n in (d.get(key) or {}).items():
                        out[key][k] = out[key].get(k, 0) + n
                bh["agents"] += sum((d.get("agents") or {}).values())
        for key, top in (("models", 10), ("tools", 15), ("agents", 12)):
            out[key] = sorted(out[key].items(), key=lambda kv: -kv[1])[:top]
        return out


# ---------------------------------------------------------------- utilitários sem estado
SECRET_KEYS = ("ntfy_topic",)


def public_settings(s, secrets_ok):
    """Ajustes para leitura: sem os segredos (tópico ntfy) para quem não está autenticado."""
    s = dict(s)
    if not secrets_ok:
        for k in SECRET_KEYS:
            s[k + "_set"] = bool(s.get(k))
            s[k] = ""
    return s


def clock_offset(d, mid, date_header):
    """Quanto o relógio do coletor está adiantado em relação a este (s). served_at > ts > Date."""
    for k in ("served_at", "ts"):
        v = d.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v) - mid
    if date_header:
        try:
            off = parsedate_to_datetime(date_header).timestamp() - mid
            return off if abs(off) >= 5 else 0.0          # o Date tem resolução de 1 s
        except (TypeError, ValueError, IndexError):
            pass
    return 0.0


def unskew_session(d, off):
    """Traz os horários do detalhe da sessão para o relógio deste painel."""
    if abs(off) < 2:
        return

    def fix(o, keys):
        for k in keys:
            v = o.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v:
                o[k] = v - off
    s = d["session"]
    fix(s, ("since", "last", "started", "started_at"))
    for a in s.get("subagents") or []:
        if isinstance(a, dict):
            fix(a, ("since", "last", "started", "started_at", "ts"))
    for e in d.get("events") or []:
        if isinstance(e, dict):
            fix(e, ("ts",))
    if isinstance(d.get("first_event"), dict):
        fix(d["first_event"], ("ts",))
    elif isinstance(d.get("first_event"), (int, float)):
        d["first_event"] -= off
    fix(d, ("served_at", "ts"))


class BadRequest(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status, self.msg = status, msg


def check_settings_patch(data):
    """Valida um patch de ajustes vindo do navegador: tipo errado = 400 (não vira padrão em silêncio)."""
    if not isinstance(data, dict):
        raise BadRequest(400, "esperado um objeto JSON")
    out = {}
    for k, v in data.items():
        if k not in SCHEMA or k == "force":
            continue
        _, typ, lo, hi = SCHEMA[k]
        try:
            if typ == "int":
                if isinstance(v, bool) or not isinstance(v, (int, float, str)):
                    raise ValueError
                f = float(v)
                if not math.isfinite(f):
                    raise ValueError
                v = int(f)
            elif typ == "bool":
                v = as_bool(v)
            elif typ == "choice":
                if v not in lo:
                    raise ValueError
            elif typ == "list":
                if not isinstance(v, list) or not all(isinstance(x, str) for x in v) or \
                        (lo is not None and any(x not in lo for x in v)):
                    raise ValueError
            elif typ == "dict":
                if not isinstance(v, dict):
                    raise ValueError
            elif typ == "str":
                if not isinstance(v, str):
                    raise ValueError
        except (TypeError, ValueError, OverflowError):
            raise BadRequest(400, f"valor inválido para {k}")
        out[k] = v
    if "colors" in out:
        bad = [h for h, c in out["colors"].items() if not valid_color(c)]
        if bad:
            raise BadRequest(400, "cor inválida (use #rrggbb)")
    if out.get("ntfy_server") and not re.match(r"^https?://", out["ntfy_server"], re.I):
        raise BadRequest(400, "servidor ntfy precisa começar com http:// ou https://")
    if "account_labels" in out:
        al = out["account_labels"]
        if len(al) > 50 or not all(account_label_ok(k, v) for k, v in al.items()):
            raise BadRequest(400, f"rótulo de conta inválido (até {LABEL_MAX} caracteres, sem caracteres de controle)")
        out["account_labels"] = {k: " ".join(v.split()) for k, v in al.items() if v.strip()}   # "" = volta ao padrão
    return out


def valid_force_mode(mode):
    if mode.startswith("layout:"):
        return mode[7:] in LAYOUT_NAMES
    return mode in SCENES


PANEL = None
MAX_BODY = 64 * 1024
PUBLIC_GET = ("/img/icon.png", "/favicon.ico")
PEER_POST = ("/api/sync", "/api/peers/add", "/api/peers/remove")

LOGIN_PAGE = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Byorzin Monitor</title>
<link rel="icon" href="/img/icon.png">
<style>body{margin:0;background:#0a0c12;color:#e8ebf2;font:15px/1.5 system-ui,sans-serif;display:flex;
min-height:100vh;align-items:center;justify-content:center;padding:20px;box-sizing:border-box}
.b{max-width:560px;background:#141824;border:1px solid #262d42;border-radius:14px;padding:22px 26px}
h1{font-size:19px;margin:0 0 10px}code{background:#0e121c;border:1px solid #262d42;border-radius:6px;padding:2px 6px}
p{margin:8px 0}small{color:#8a93ab}img{width:48px;height:48px;float:right}</style></head><body><div class="b">
<img src="/img/icon.png" alt="">
<h1>Byorzin Monitor: acesso pela rede</h1>
<p>Para abrir este painel em outro aparelho, use o <b>link com a chave do painel</b>. Na máquina do painel:</p>
<p>&bull; abra <code>http://localhost:PORT</code> &rarr; <b>Máquinas</b> &rarr; <b>Acesso de outro aparelho</b>; ou<br>
&bull; rode <code>byorzin-monitor panel-url</code> (ou <code>curl http://127.0.0.1:PORT/api/panel-url</code>).</p>
<p>Abra o link uma vez neste aparelho; ele fica lembrado (cookie).</p>
<hr style="border:0;border-top:1px solid #262d42">
<p lang="en"><small><b>Network access.</b> Open this panel from another device with the <b>panel link with key</b>:
on the panel's machine open <code>http://localhost:PORT</code> &rarr; <b>Machines</b> &rarr; <b>Access from another device</b>,
or run <code>byorzin-monitor panel-url</code>. Open the link once; this device remembers it.</small></p>
</div></body></html>"""

ENTER_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Byorzin Monitor</title></head>
<body style="background:#0a0c12;color:#8a93ab;font:15px system-ui,sans-serif">
<p>entrando… <a id="go" href="/">continuar</a></p>
<script>const u=TARGET;document.getElementById('go').href=u;location.replace(u+location.hash);</script>
</body></html>"""


class H(BaseHTTPRequestHandler):
    timeout = 30                    # conexão parada não prende uma thread para sempre
    server_version = "byorzin-panel"
    sys_version = ""

    def log_message(self, *a):
        pass

    # ------------------------------------------------ respostas
    def send(self, code, body, ctype="application/json", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def send_page(self, html, code=200, headers=None, frame=False):
        """HTML com CSP: scripts só com o nonce desta resposta (nada de JS inline com dados)."""
        nonce = secrets.token_urlsafe(16)
        html = html.replace("<script>", f'<script nonce="{nonce}">')
        h = {"Content-Security-Policy":
             f"default-src 'self'; script-src 'nonce-{nonce}'; style-src 'self' 'unsafe-inline'; "
             f"img-src 'self' blob: data:; connect-src 'self'; base-uri 'none'; form-action 'self'; "
             f"object-src 'none'" + ("" if frame else "; frame-ancestors 'none'")}
        if not frame:
            h["X-Frame-Options"] = "DENY"
        h.update(headers or {})
        self.send(code, html, "text/html; charset=utf-8", h)

    def err(self, code, msg):
        return self.send(code, {"erro": msg})

    def body(self):
        if self.headers.get("Transfer-Encoding"):
            self.close_connection = True
            raise BadRequest(411, "envie Content-Length")
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.close_connection = True
            raise BadRequest(400, "Content-Length inválido")
        if n < 0:
            self.close_connection = True
            raise BadRequest(400, "Content-Length inválido")
        if n > MAX_BODY:
            self.close_connection = True
            raise BadRequest(413, "corpo grande demais")
        raw = self.rfile.read(n) if n else b""
        try:
            data = json.loads(raw or b"{}")
        except (ValueError, UnicodeDecodeError):
            raise BadRequest(400, "json inválido")
        if not isinstance(data, dict):
            raise BadRequest(400, "esperado um objeto JSON")
        return data

    def png(self, img):
        buf = io.BytesIO()
        img.save(buf, "PNG")
        self.send(200, buf.getvalue(), "image/png")

    # ------------------------------------------------ quem está pedindo
    def port(self):
        return self.server.server_address[1]

    def local(self):
        try:
            sip = self.connection.getsockname()[0]
        except OSError:
            sip = None
        return auth.is_local(self.client_address[0], self.headers.get("Host"), sip)

    def authed(self):
        """'local' | 'key' (cookie ou ?key) | 'peer' (token do grupo) | 'open' (panel_auth=off) | None."""
        if self.local():
            return "local"
        if auth.cookie_ok(self.headers.get("Cookie"), self.port()):
            return "key"
        if auth.bearer_ok(self.headers.get("Authorization"), PANEL.cfg.get("token")):
            return "peer"
        if getattr(self, "_key_ok", False):
            return "key"
        if PANEL.auth_mode == "off":
            return "open"
        return None

    def csrf_ok(self):
        """POST de navegador de outro site não passa: exige JSON, o cabeçalho próprio e Origin = Host."""
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return False
        if self.headers.get(auth.CSRF_HEADER) != "1":
            return False
        return auth.origin_ok(self.headers.get("Origin"), self.headers.get("Host"))

    # ------------------------------------------------ GET
    def do_GET(self):
        try:
            self._get()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except BadRequest as e:
            self._safe_err(e.status, e.msg)
        except Exception as e:
            print("erro no painel (GET):", repr(e), file=sys.stderr, flush=True)
            self._safe_err(500, "erro interno")

    def _safe_err(self, code, msg):
        try:
            self.err(code, msg)
        except Exception:
            self.close_connection = True

    def _get(self):
        self._key_ok = False
        u = urlparse(self.path)
        q = parse_qs(u.query)
        p = u.path
        key = (q.get("key") or [None])[0]
        if key is not None:
            if not auth.key_ok(key):
                return self.send_page(LOGIN_PAGE.replace("PORT", str(self.port())), 401)
            self._key_ok = True
            if p in ("/", "/tela", "/tela/"):
                # troca a chave por um cookie e tira a chave da URL (fica fora do histórico)
                rest = [(k, v) for k, vs in q.items() if k != "key" for v in vs]
                target = p + ("?" + urlencode(rest) if rest else "")
                page = ENTER_PAGE.replace("TARGET", json.dumps(target).replace("<", "\\u003c"))
                return self.send_page(page, headers={"Set-Cookie": auth.set_cookie_header(self.port())})
        if p in PUBLIC_GET:
            return self.png(S.sprite(64, "idle", 0.25, None, False, False, (0, 0), "66 50 68 68"))
        who = self.authed()
        if who is None:
            if p in ("/", "/tela", "/tela/"):
                return self.send_page(LOGIN_PAGE.replace("PORT", str(self.port())), 401)
            return self.err(401, "precisa do link com a chave do painel")
        secrets_ok = who in ("local", "key", "peer")
        if p == "/":
            return self.send_page(PAGE)
        if p == "/api/state":
            return self.send(200, PANEL.state(secrets_ok, local=who == "local"))
        if p == "/api/panel-url":
            if who != "local":
                return self.err(403, "só no navegador desta máquina")
            return self.send(200, auth.panel_links(self.port()))
        # --- tela no navegador (backend web) e saídas disponíveis ---
        if p.startswith("/tela"):
            from byorzin_monitor.display.backends import web
            if web.handle(self, p, q, web.hub_for(PANEL)):
                return
        if p == "/api/telas":
            from byorzin_monitor.display.backends import available
            name, port = auth.split_host(self.headers.get("Host"))
            host = f"{name}:{port}" if port else name
            if not re.match(r"^[a-z0-9.\-:\[\]]+$", host):
                host = f"127.0.0.1:{self.port()}"
            return self.send(200, available(f"http://{host}"))
        # --- fim tela no navegador ---
        if p == "/api/history":
            try:
                n = int(q.get("days", ["30"])[0])
            except ValueError:
                n = 30
            return self.send(200, PANEL.history(n))
        if p == "/api/session":
            d = PANEL.session(q.get("host", [""])[0], q.get("id", [""])[0])
            return self.send(200, d) if d else self.err(404, "sessão não encontrada")
        if p == "/api/machines":
            return self.send(200, {"machine": PANEL.cfg["hostname"], "paired": PANEL.machines(), **PANEL.net_state()})
        if p == "/img/now-local.png":
            b = PANEL.frame_local()
            return self.send(200, b, "image/png") if b else self.send(404, b"", "text/plain")
        if p == "/img/now.png":
            b, where = PANEL.frame_any()
            if not b:
                return self.send(404, b"", "text/plain")
            return self.send(200, b, "image/png", {"X-Byorzin-Screen": quote(str(where or ""), safe="")})
        parts = p.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "img" and parts[2].endswith(".png"):
            kind, name = parts[1], parts[2][:-4]
            if (kind == "layout" and name in LAYOUTS) or (kind == "scene" and name in SCENES):
                # ?scale=1..4: prévia em alta resolução (480K x 320K); padrão 1, como sempre
                with PANEL.lock, S.scaled(S.clamp_scale((q.get("scale") or ["1"])[0])):
                    img = PANEL.render(kind, name, q.get("data", ["demo"])[0])
                if img is not None:
                    return self.png(img)
        self.send(404, b"", "text/plain")

    # ------------------------------------------------ POST
    def do_POST(self):
        try:
            self._post()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except BadRequest as e:
            self._safe_err(e.status, e.msg)
        except pairing.PairError as e:
            self._safe_err(e.status, e.msg)
        except Exception as e:
            print("erro no painel (POST):", repr(e), file=sys.stderr, flush=True)
            self._safe_err(500, "erro interno")

    def _post(self):
        path = urlparse(self.path).path
        data = self.body()
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if path in PEER_POST:                       # entre máquinas pareadas: token do grupo
            if not auth.bearer_ok(self.headers.get("Authorization"), PANEL.cfg.get("token")):
                return self.err(401, "token")
            if ctype != "application/json":
                return self.err(415, "use application/json")
            if path == "/api/sync":
                return self.send(200, {"ok": True, "applied": PANEL.apply_remote(data)})
            return self.peers_post(path, data)
        if not self.csrf_ok():
            return self.err(403, "pedido recusado (proteção contra CSRF)")
        if path == "/api/pair/claim":               # outra máquina trocando o código (público, com limites)
            resp, b = pairing.accept(PANEL.pairing, self.client_address[0], data, PANEL.cfg)
            threading.Thread(target=pairing.tell_peers, args=(resp["peers"], b, resp["token"]), daemon=True).start()
            print(f"pareado com {b['host']} ({b['url']})", file=sys.stderr, flush=True)
            return self.send(200, resp)
        who = self.authed()
        if who is None:
            return self.err(401, "precisa do link com a chave do painel")
        secrets_ok = who in ("local", "key", "peer")
        if path == "/api/settings":
            patch = check_settings_patch(data)
            if not secrets_ok:
                for k in SECRET_KEYS:          # quem não vê o tópico não o apaga sem querer
                    if patch.get(k) == "":
                        patch.pop(k)
            new = PANEL.update(patch)
            return self.send(200, {"ok": True, "settings": public_settings(new, secrets_ok), "synced_to": PANEL.peers})
        if path == "/api/force":
            mode = data.get("mode") or ""
            if not isinstance(mode, str) or (mode and not valid_force_mode(mode)):
                return self.err(400, "modo inválido")
            secs = data.get("seconds", 15)
            if isinstance(secs, bool) or not isinstance(secs, (int, float, str)):
                return self.err(400, "seconds inválido")
            try:
                secs = float(secs)
            except ValueError:
                return self.err(400, "seconds inválido")
            if not math.isfinite(secs):
                return self.err(400, "seconds inválido")
            secs = max(3, min(120, secs))
            force = {"mode": mode, "until": time.time() + secs} if mode else {}
            return self.send(200, {"ok": True, "settings": public_settings(PANEL.update({"force": force}), secrets_ok)})
        if path == "/api/panel-key/rotate":
            if who != "local":
                return self.err(403, "só no navegador desta máquina")
            auth.rotate_key()
            return self.send(200, {"ok": True, **auth.panel_links(self.port())})
        if path.startswith(("/api/pair/", "/api/machines/")):
            if who == "open" and not PANEL.allowed_legacy(self):
                return self.err(403, "por segurança, isso só pode ser feito no painel desta máquina "
                                     "(ou de uma máquina já pareada)")
            return self.machines_post(path, data)
        self.err(404, "rota")

    def peers_post(self, path, data):
        if path == "/api/peers/add":
            url = net.norm_url(str(data.get("url") or ""), 8787)
            if not re.match(r"^https?://[^/\s]+$", url):
                return self.err(400, "url inválida")
            panel = str(data.get("panel") or "")
            if panel and not re.match(r"^https?://[^/\s]+$", panel):
                panel = ""
            url = net.add_peer(url, str(data.get("host") or "")[:64], str(data.get("id") or "")[:40], panel)
            return self.send(200, {"ok": True, "url": url})
        try:
            port = int(data.get("port") or 8787)
        except (TypeError, ValueError):
            return self.err(400, "porta inválida")
        gone = net.remove_peer(f"http://{self.client_address[0]}:{port}", str(data.get("id") or "") or None)
        return self.send(200, {"ok": True, "removed": gone})

    # ------------------------------------------------ máquinas: pareamento e despareamento
    def machines_post(self, path, data):
        if path == "/api/pair/code":
            return self.send(200, PANEL.pairing.generate())
        if path == "/api/pair/cancel":
            PANEL.pairing.cancel()
            return self.send(200, {"ok": True})
        if path == "/api/pair/join":             # esta máquina entra no grupo de outra (ação do usuário)
            target = str(data.get("target") or "").strip()
            if not target:
                return self.err(400, "informe o endereço da outra máquina")
            return self.send(200, {"ok": True, **pairing.join(target, data.get("code"), PANEL.cfg)})
        if path == "/api/machines/remove":
            url = net.norm_url(str(data.get("url") or ""))
            if not url:
                return self.err(400, "máquina não informada")
            cfg = PANEL.cfg
            # só máquinas pareadas: o token do grupo nunca vai para um endereço vindo do pedido
            if url not in PANEL.peer_urls():
                return self.err(404, "essa máquina não está pareada")
            try:
                pairing.post(net.panel_of(url, cfg) + "/api/peers/remove",
                             {"id": PANEL.mid, "port": int(cfg.get("port", 8787))}, token=cfg.get("token"), timeout=3)
                other = True
            except pairing.PairError:
                other = False
            return self.send(200, {"ok": True, "removed": net.remove_peer(url), "other_side": other})
        return self.err(404, "rota")


def main():
    global PANEL
    global PORT
    cfg = load_config()
    PORT = int(cfg.get("panel_port", PORT))
    bind = str(cfg.get("panel_bind", "0.0.0.0"))
    srv = ThreadingHTTPServer((bind, PORT), H)    # porta ocupada falha aqui, antes de subir as threads
    PANEL = Panel()
    auth.panel_key()                      # cria a chave já na subida
    print(f"painel em http://{bind}:{PORT} (acesso pela rede: {PANEL.auth_mode}; "
          f"link com a chave: byorzin-monitor panel-url ou http://127.0.0.1:{PORT}/api/panel-url)",
          file=sys.stderr, flush=True)
    srv.serve_forever()


PAGE = (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")

if __name__ == "__main__":
    if sys.argv[1:] == ["url"]:
        print(auth.panel_links(int(load_config().get("panel_port", PORT)))["url"])
    else:
        main()
