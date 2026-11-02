# Alertas: "esperando você" e "terminou". Roda dentro do coletor, alimentado pelos eventos dos hooks.
# Só o coletor da máquina dona da sessão vê os eventos dela, então só ele avisa (ntfy incluso):
# com várias máquinas não há aviso duplicado. Tela e painel só leem `alerts` do /state.
import json
import sys
import threading
import time
import urllib.request

WAIT_NOTIF = {"permission_prompt": "permissão", "elicitation_dialog": "pergunta", "idle_prompt": "ociosa"}
BUSY = ("UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure", "SubagentStart",
        "SubagentStop", "PermissionDenied")
REPLAY_MAX_AGE = 60       # eventos mais velhos que isso (releitura do events.jsonl) não avisam
KEEP_SECONDS = 15 * 60    # quanto tempo um alerta fica no /state


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


def send_ntfy(server, topic, title, message, tags, priority=3, timeout=5):
    """Publica no ntfy pelo formato JSON (aceita UTF-8 no título, ao contrário dos cabeçalhos)."""
    body = json.dumps({"topic": topic, "title": title, "message": message,
                       "tags": tags, "priority": priority}, ensure_ascii=False).encode()
    req = urllib.request.Request(server.rstrip("/") + "/", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        r.read()


class Alerts:
    """Detecta transições por sessão. `settings` é uma função que devolve o dict de ajustes;
    `label` devolve o nome da sessão (título ou projeto); `clock` existe para os testes."""

    def __init__(self, host, settings, label=None, clock=time.time, sender=send_ntfy):
        self.host = host
        self.settings = settings
        self.label = label or (lambda sid: None)
        self.clock = clock
        self.sender = sender
        self.sess = {}          # sid -> {"waiting", "work_start", "last_alert": {tipo: ts}, "project"}
        self.items = []         # alertas recentes (expostos no /state)
        self.seq = 0
        self.lock = threading.Lock()
        self.sent = []          # (título, mensagem) enviados ao ntfy — útil para depurar/testes

    def on_event(self, ev):
        sid, name, ts = ev.get("session_id"), ev.get("hook_event_name"), ev.get("ts") or 0
        if not sid or not name:
            return
        s = self.sess.setdefault(sid, {"waiting": False, "work_start": None, "last_alert": {}, "project": None})
        if ev.get("project"):
            s["project"] = ev["project"]
        cfg = self.settings() or {}
        live = self.clock() - ts <= REPLAY_MAX_AGE
        if name == "PermissionRequest" or (name == "Notification" and ev.get("notification_type") in WAIT_NOTIF):
            reason = "permissão" if name == "PermissionRequest" else WAIT_NOTIF[ev["notification_type"]]
            was = s["waiting"]
            s["waiting"] = True
            if not was and live and (reason != "ociosa" or cfg.get("alert_idle", True)):
                self._fire(sid, s, "waiting", ts, cfg, reason=reason)
            return
        if name == "Notification":
            return
        s["waiting"] = False
        if name in BUSY:
            if s["work_start"] is None:
                s["work_start"] = ts
        elif name in ("Stop", "StopFailure"):
            ws, s["work_start"] = s["work_start"], None
            worked = ts - ws if ws else 0
            if name == "Stop" and live and worked >= cfg.get("done_minutes", 5) * 60:
                self._fire(sid, s, "done", ts, cfg, worked_s=round(worked))
        elif name == "SessionEnd":
            self.sess.pop(sid, None)

    def _fire(self, sid, s, typ, ts, cfg, reason=None, worked_s=None):
        now = self.clock()
        cool = cfg.get("alert_cooldown_seconds", 90)
        # intervalo mínimo por sessão e tipo; "ociosa" logo depois de um "terminou" é redundante
        last = s["last_alert"].get(typ, 0)
        if reason == "ociosa":
            last = max(last, s["last_alert"].get("done", 0))
        if now - last < cool:
            return
        s["last_alert"][typ] = now
        label = self.label(sid) or s["project"] or sid[:8]
        self.seq += 1
        a = {"key": f"{self.host}:{sid}:{self.seq}:{int(now)}", "ts": now, "type": typ, "session_id": sid,
             "project": s["project"], "label": label, "host": self.host}
        if reason:
            a["reason"] = reason
        if worked_s is not None:
            a["worked_s"] = worked_s
        with self.lock:
            self.items.append(a)
            self.items = [x for x in self.items if now - x["ts"] < KEEP_SECONDS][-30:]
        self._ntfy(a, cfg)

    def _ntfy(self, a, cfg):
        if not cfg.get("ntfy_enabled") or not cfg.get("ntfy_topic") or not cfg.get("ntfy_server"):
            return
        if not cfg.get("ntfy_waiting" if a["type"] == "waiting" else "ntfy_done", True):
            return
        # por privacidade vai só o nome do projeto (o título da sessão pode revelar o assunto)
        where = f"{a.get('project') or 'sessão'} @ {self.host}"
        if a["type"] == "waiting":
            title, msg, tags, prio = "Esperando você", f"{where} ({a.get('reason', 'atenção')})", ["hourglass"], 4
        else:
            title, msg, tags, prio = "Terminou", f"{where} em {a['worked_s'] // 60} min", ["tada"], 3
        self.sent.append((title, msg))
        del self.sent[:-20]

        def go():
            try:
                self.sender(cfg["ntfy_server"], cfg["ntfy_topic"], title, msg, tags, prio)
            except Exception as e:
                log("ntfy falhou:", repr(e))
        threading.Thread(target=go, daemon=True).start()

    def recent(self):
        now = self.clock()
        with self.lock:
            return [dict(x) for x in self.items if now - x["ts"] < KEEP_SECONDS]
