# cm-collector: junta sessões, eventos (hooks), limites (status line), tokens (transcripts)
# e métricas do host, e serve tudo em GET /state. Só biblioteca padrão.
import hmac
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from byorzin_monitor.account import identify as identify_account, rate_accounts, valid_id as valid_account
from byorzin_monitor.common import (CLAUDE_DIR, EVENTS_FILE, RATE_FILE, SESSION_INFO_DIR, TOKENS_FILE,
                     ensure_state_dir, load_config, read_json, write_json_atomic)

EVENTS_MAX_BYTES = 5 * 1024 * 1024
TOKEN_WINDOW = 8 * 86400          # mantém baldes por hora dos últimos 8 dias
SUBAGENT_STALE = 30 * 60
ACCOUNT_STALE = 24 * 3600         # outra conta que usou esta máquina: some de /state depois disso
RECENT_MAX = 60
SEEN_MAX = 50000                  # ids de mensagens lembrados (evita contar a mesma resposta 2x)
WAIT_TYPES = ("permission_prompt", "idle_prompt", "elicitation_dialog")
# eventos da sessão principal que mudam o status (usados para ignorar os que chegam atrasados)
STATUS_EVENTS = ("PreToolUse", "PostToolUse", "UserPromptSubmit", "PermissionDenied", "PostToolUseFailure",
                 "Notification", "PermissionRequest", "Stop", "StopFailure", "SessionStart")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- sessões
def _pid_alive(pid, proc_start):
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    if proc_start:
        start = stat.rsplit(")", 1)[1].split()[19]
        return start == str(proc_start)
    return True


def read_sessions():
    out = {}
    for f in (CLAUDE_DIR / "sessions").glob("*.json"):
        d = read_json(f)
        if not isinstance(d, dict) or "sessionId" not in d:
            continue
        if not _pid_alive(d.get("pid"), d.get("procStart")):
            continue
        cwd = d.get("cwd") or ""
        out[d["sessionId"]] = {
            "id": d["sessionId"],
            "project": os.path.basename(cwd.rstrip("/")) or "/",
            "since": (d.get("startedAt") or 0) / 1000,
            "kind": d.get("kind"),
        }
    return out


# ---------------------------------------------------------------- leitura incremental
READ_BLOCK = 4 * 1024 * 1024


def read_lines(path, off, fn, block=READ_BLOCK):
    """Lê `path` a partir de `off` em blocos (sem carregar o arquivo inteiro na memória) e chama
    fn(linha) para cada linha completa. Devolve o novo offset (fim da última linha completa)."""
    pos = off
    buf = b""
    with open(path, "rb") as fh:
        fh.seek(off)
        while True:
            chunk = fh.read(block)
            if not chunk:
                break
            buf += chunk
            end = buf.rfind(b"\n")
            if end < 0:
                continue
            for ln in buf[:end].split(b"\n"):
                fn(ln)
            pos += end + 1
            buf = buf[end + 1:]
    return pos


# ---------------------------------------------------------------- títulos
class Titles:
    """Título de cada sessão = o mesmo da aba do terminal: o Claude Code grava linhas
    `ai-title` (gerado) e `custom-title` (quando a sessão é renomeada) no transcript."""

    def __init__(self):
        self.cache = {}         # session_id -> {"off": bytes lidos, "ai": ..., "custom": ...}

    def get(self, sid):
        c = self.cache.setdefault(sid, {"off": 0, "ai": None, "custom": None, "path": None})
        if c["path"] is None:
            files = list((CLAUDE_DIR / "projects").glob(f"*/{sid}.jsonl"))
            if not files:
                return None
            c["path"] = files[0]
        try:
            size = c["path"].stat().st_size
            if size < c["off"]:
                c.update(off=0, ai=None, custom=None)
            if size > c["off"]:
                def take(ln):
                    if b'"ai-title"' in ln or b'"custom-title"' in ln:
                        try:
                            d = json.loads(ln)
                        except Exception:
                            return
                        if d.get("type") == "custom-title" and d.get("customTitle"):
                            c["custom"] = d["customTitle"]
                        elif d.get("type") == "ai-title" and d.get("aiTitle"):
                            c["ai"] = d["aiTitle"]
                # transcript só cresce: lê só o que é novo, em blocos
                c["off"] = read_lines(c["path"], c["off"], take)
        except OSError:
            return None
        return ((c["custom"] or c["ai"] or "").strip()[:80]) or None


# ---------------------------------------------------------------- eventos
class EventState:
    """Estado vivo por sessão, reconstruído a partir do events.jsonl."""

    def __init__(self):
        self.sess = {}              # session_id -> dict
        self.recent = []            # últimos eventos (para reações na tela)
        self.last_activity = 0.0
        self._fh = None
        self._ino = None
        self.listeners = []         # funções chamadas com cada evento cru (alertas, histórico...)
        self.ended = {}             # session_id -> ts do SessionEnd (ignora eventos atrasados)

    @staticmethod
    def _unwait(s, aid, ts):
        """O agente que deixou a sessão "esperando você" voltou a trabalhar (ou terminou)."""
        if s["status"] == "waiting" and s.get("wait_by") == aid and ts >= s["status_ts"]:
            status, tool = s.get("pre_wait") or ("working", None)
            s.update(status=status, tool=tool, wait_by=None, pre_wait=None, status_ts=ts)

    def _s(self, sid):
        return self.sess.setdefault(sid, {"status": "idle", "tool": None, "subagents": {}, "gone": {},
                                          "last": 0, "mood_until": 0, "mood": None, "project": None,
                                          "status_ts": 0, "wait_by": None, "pre_wait": None})

    def apply(self, ev):
        """Aplica um evento. Os hooks são assíncronos (um processo por evento), então as linhas
        podem chegar fora de ordem: transições com ts anterior à última aplicada são ignoradas, e
        subagentes encerrados ficam marcados ("tombstones") para eventos atrasados não os recriarem."""
        sid, name, ts = ev.get("session_id"), ev.get("hook_event_name"), ev.get("ts", 0) or 0
        if not sid or not name:
            return
        for f in self.listeners:
            try:
                f(ev)
            except Exception as e:
                log("erro num ouvinte de eventos:", repr(e))
        if ts < self.ended.get(sid, 0):        # evento atrasado de uma sessão já encerrada
            return
        s = self._s(sid)
        s["last"] = max(s["last"], ts)
        if ev.get("project"):
            s["project"] = ev["project"]
        self.last_activity = max(self.last_activity, ts)
        aid = ev.get("agent_id")
        late = ts < s["status_ts"]               # chegou depois de um evento mais novo da sessão
        if aid and aid in s["gone"]:             # subagente já encerrado: evento atrasado
            pass
        elif name == "SubagentStart" and aid:
            # setdefault: um evento do agente pode ter chegado antes do próprio SubagentStart
            sub = s["subagents"].setdefault(aid, {"type": None, "tool": None, "last": ts, "waiting": False})
            sub["type"] = sub.get("type") or ev.get("agent_type")
            sub["last"] = max(sub["last"], ts)
        elif name == "SubagentStop" and aid:
            s["subagents"].pop(aid, None)
            s["gone"][aid] = ts
            if len(s["gone"]) > 500:
                for k in sorted(s["gone"], key=s["gone"].get)[:len(s["gone"]) - 500]:
                    s["gone"].pop(k)
            self._unwait(s, aid, ts)
        elif aid and name in ("PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest", "Notification",
                              "PermissionDenied"):
            # evento de dentro de um subagente: a ferramenta é do agente, nunca da sessão. Se o
            # SubagentStart se perdeu (coletor reiniciado etc.), registra o agente aqui mesmo.
            sub = s["subagents"].setdefault(aid, {"type": ev.get("agent_type"), "tool": None, "last": 0,
                                                 "waiting": False})
            if ts >= sub["last"]:
                asks = name == "PermissionRequest" or (name == "Notification" and ev.get("notification_type") in WAIT_TYPES)
                if asks:
                    sub.update(tool=None, waiting=True, last=ts)
                    # o agente parou esperando você: a sessão inteira fica "esperando você"
                    # (mesmo que a sessão tenha eventos mais novos: eles não respondem ao pedido do agente)
                    if s["status"] != "waiting":
                        s["pre_wait"] = (s["status"], s["tool"])
                        s.update(status="waiting", tool=None, wait_by=aid)
                    s["status_ts"] = max(s["status_ts"], ts)
                elif name == "Notification":
                    sub["last"] = ts
                else:
                    sub.update(tool=ev.get("tool_name") if name == "PreToolUse" else None, waiting=False, last=ts)
                    self._unwait(s, aid, ts)
        elif late and name not in ("SessionEnd",):
            pass                                 # transição velha: não desfaz o estado atual
        elif name == "PreToolUse":
            s.update(status="working", tool=ev.get("tool_name"))
        elif name in ("PostToolUse", "UserPromptSubmit", "PermissionDenied"):
            s.update(status="working", tool=None)
        elif name == "PostToolUseFailure":
            s.update(status="working", tool=None, mood="sad", mood_until=ts + 4)
        elif name in ("Notification", "PermissionRequest"):
            if name == "PermissionRequest" or ev.get("notification_type") in WAIT_TYPES:
                s.update(status="waiting", tool=None, wait_by=None, pre_wait=None)
        elif name == "Stop":
            # o turno principal acabou, mas agentes em segundo plano podem continuar rodando:
            # eles só saem com SubagentStop (ou por inatividade, SUBAGENT_STALE)
            s.update(status="idle", tool=None, mood="happy", mood_until=ts + 5)
        elif name == "StopFailure":
            s.update(status="error" if ev.get("error") != "rate_limit" else "limit", tool=None,
                     mood="sad", mood_until=ts + 6)
        elif name == "SessionEnd":
            self.sess.pop(sid, None)
            self.ended[sid] = ts
            if len(self.ended) > 2000:
                for k in sorted(self.ended, key=self.ended.get)[:len(self.ended) - 2000]:
                    self.ended.pop(k)
        elif name == "SessionStart":
            s.update(status="idle", tool=None)
        if sid in self.sess and not late and not aid and name in STATUS_EVENTS:
            s["status_ts"] = ts
            if s["status"] != "waiting":
                s.update(wait_by=None, pre_wait=None)
        if name not in ("PostToolUse", "SessionEnd"):
            r = {k: ev.get(k) for k in ("ts", "session_id", "hook_event_name", "tool_name", "agent_type",
                                        "notification_type", "error") if ev.get(k) is not None}
            r["project"] = s.get("project")
            r["sub"] = bool(aid)
            self.recent.append(r)
            del self.recent[:-RECENT_MAX]

    def poll(self):
        """Lê linhas novas do events.jsonl; rotaciona quando passa do tamanho máximo."""
        try:
            st = os.stat(EVENTS_FILE)
        except FileNotFoundError:
            return
        if self._fh is None or st.st_ino != self._ino:
            if self._fh:
                self._drain()
                self._fh.close()
            self._fh = open(EVENTS_FILE, "rb")
            self._ino = st.st_ino
            self._buf = b""
        self._drain()
        if st.st_size > EVENTS_MAX_BYTES:
            os.replace(EVENTS_FILE, str(EVENTS_FILE) + ".1")

    def _drain(self):
        chunk = self._fh.read()
        if not chunk:
            return
        data = self._buf + chunk
        lines = data.split(b"\n")
        self._buf = lines.pop()
        for ln in lines:
            try:
                self.apply(json.loads(ln))
            except Exception:
                pass


# ---------------------------------------------------------------- tokens
class TokenCounter:
    """Soma message.usage dos transcripts, de forma incremental, em baldes por hora."""

    def __init__(self):
        saved = read_json(TOKENS_FILE, {}) or {}
        self.offsets = saved.get("offsets", {})
        self.hours = {int(k): v for k, v in saved.get("hours", {}).items()}
        self.sessions = saved.get("sessions", {})          # sessionId -> tokens (8 dias)
        self.days = saved.get("days", {})                  # "AAAA-MM-DD" -> tokens (histórico)
        self.models = {int(k): v for k, v in saved.get("models", {}).items()}
        # ids de mensagens já contadas, em ordem de chegada (dict mantém a ordem: os mais novos no fim)
        self.seen = dict.fromkeys(saved.get("seen", []))

    def save(self):
        if len(self.seen) > SEEN_MAX:             # descarta os mais antigos
            for k in list(self.seen)[:len(self.seen) - SEEN_MAX]:
                del self.seen[k]
        write_json_atomic(TOKENS_FILE, {"offsets": self.offsets, "hours": self.hours, "sessions": self.sessions,
                                        "days": self.days, "models": self.models, "seen": list(self.seen)})

    def scan(self):
        cutoff = time.time() - TOKEN_WINDOW
        changed = False
        present = set()
        for f in (CLAUDE_DIR / "projects").glob("**/*.jsonl"):
            key = str(f)
            present.add(key)
            try:
                st = f.stat()
            except OSError:
                continue
            if st.st_mtime < cutoff:
                continue
            off = self.offsets.get(key, 0)
            if st.st_size < off:
                off = 0
            if st.st_size == off:
                continue
            try:
                new = read_lines(f, off, self._take)
            except OSError:
                continue
            if new != off:
                self.offsets[key] = new
                changed = True
        for key in [k for k in self.offsets if k not in present]:   # transcript apagado
            self.offsets.pop(key)
            changed = True
        self._prune(cutoff)
        if changed:
            self.save()
        return changed

    def _take(self, ln):
        if b'"usage"' in ln:
            self._line(ln)

    def _line(self, ln):
        try:
            d = json.loads(ln)
        except Exception:
            return
        m = d.get("message")
        if d.get("type") != "assistant" or not isinstance(m, dict) or not isinstance(m.get("usage"), dict):
            return
        mid = (m.get("id") or "") + ":" + (d.get("requestId") or "")
        if mid in self.seen:
            return
        self.seen[mid] = None
        u = m["usage"]
        tot = sum(int(u.get(k) or 0) for k in ("input_tokens", "output_tokens",
                                                "cache_creation_input_tokens", "cache_read_input_tokens"))
        if not tot:
            return
        try:
            ts = datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).timestamp()
        except Exception:
            ts = time.time()
        h = int(ts // 3600 * 3600)
        b = self.hours.setdefault(h, {"tot": 0, "out": 0})
        b["tot"] += tot
        b["out"] += int(u.get("output_tokens") or 0)
        sid = d.get("sessionId")
        if sid:
            self.sessions[sid] = self.sessions.get(sid, 0) + tot
        day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        self.days[day] = self.days.get(day, 0) + tot
        model = (m.get("model") or "?").replace("claude-", "")
        mb = self.models.setdefault(h, {})
        mb[model] = mb.get(model, 0) + tot

    def _prune(self, cutoff):
        for h in [h for h in self.hours if h < cutoff]:
            self.hours.pop(h)
            self.models.pop(h, None)
        live = {Path(k).stem for k in self.offsets}
        for sid in [s for s in self.sessions if s not in live]:
            self.sessions.pop(sid)

    def summary(self, week_start):
        midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        today = sum(b["tot"] for h, b in self.hours.items() if h >= midnight)
        week = sum(b["tot"] for h, b in self.hours.items() if h >= week_start)
        by_model = {}
        for h, mb in self.models.items():
            if h >= week_start:
                for k, v in mb.items():
                    by_model[k] = by_model.get(k, 0) + v
        rec = max(self.days.items(), key=lambda kv: kv[1]) if self.days else None
        h_now = int(time.time() // 3600 * 3600)
        hourly = [self.hours.get(h_now - i * 3600, {}).get("tot", 0) for i in range(23, -1, -1)]
        return {"today": today, "week": week, "by_model": by_model, "hourly": hourly,
                "record_day": {"date": rec[0], "tokens": rec[1]} if rec else None}


# ---------------------------------------------------------------- host
class HostMetrics:
    def __init__(self, ollama_url="http://127.0.0.1:11434"):
        self._cpu = None
        self.data = {}
        self.ollama_url = (ollama_url or "http://127.0.0.1:11434").rstrip("/")

    def _cpu_pct(self):
        v = list(map(int, Path("/proc/stat").read_text().split("\n", 1)[0].split()[1:]))
        idle, total = v[3] + v[4], sum(v)
        prev, self._cpu = self._cpu, (idle, total)
        if not prev or total == prev[1]:
            return None
        return round(100 * (1 - (idle - prev[0]) / (total - prev[1])), 1)

    def collect(self):
        d = {}
        try:
            d["cpu"] = self._cpu_pct()
            mi = {l.split(":")[0]: int(l.split()[1]) for l in Path("/proc/meminfo").read_text().splitlines() if l.split()[1:]}
            d["ram_used_gb"] = round((mi["MemTotal"] - mi["MemAvailable"]) / 1048576, 1)
            d["ram_total_gb"] = round(mi["MemTotal"] / 1048576, 1)
            d["uptime_s"] = int(float(Path("/proc/uptime").read_text().split()[0]))
            d["cores"] = os.cpu_count()
        except Exception:
            pass
        d["cpu_temp"] = self._cpu_temp()
        if shutil.which("nvidia-smi"):
            try:
                out = subprocess.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                                      "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5).stdout
                name, util, mu, mt, temp = [x.strip() for x in out.splitlines()[0].split(",")]
                d["gpu"] = {"name": name, "util": float(util), "mem_used_gb": round(float(mu) / 1024, 1),
                            "mem_total_gb": round(float(mt) / 1024, 1), "temp": float(temp)}
            except Exception:
                pass
        try:
            with urllib.request.urlopen(self.ollama_url + "/api/ps", timeout=1) as r:
                ms = json.load(r).get("models", [])
            d["ollama"] = [{"name": m.get("name"), "vram_gb": round((m.get("size_vram") or 0) / 2**30, 1)} for m in ms]
        except Exception:
            pass
        if shutil.which("docker"):
            try:
                out = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}\t{{.State}}\t{{.Status}}"],
                                     capture_output=True, text=True, timeout=5)
                if out.returncode == 0:
                    rows = [l.split("\t") for l in out.stdout.splitlines() if l]
                    d["docker"] = {
                        "running": sum(1 for r in rows if r[1] == "running"),
                        "stopped": sum(1 for r in rows if r[1] == "exited"),
                        "problem": [r[0] for r in rows if r[1] in ("restarting", "dead") or "unhealthy" in r[2]],
                    }
            except Exception:
                pass
        self.data = d

    @staticmethod
    def _cpu_temp():
        for hw in Path("/sys/class/hwmon").glob("hwmon*"):
            try:
                if (hw / "name").read_text().strip() in ("k10temp", "coretemp", "zenpower", "cpu_thermal"):
                    return int((hw / "temp1_input").read_text()) / 1000
            except OSError:
                continue
        return None


# ---------------------------------------------------------------- coletor
class Collector:
    def __init__(self, cfg, live=None):
        self.cfg = dict(cfg)
        self.live = live          # LiveConfig: hostname relido do config.toml sem reiniciar
        self.events = EventState()
        self.tokens = TokenCounter()
        self.host = HostMetrics(cfg.get("ollama_url") or "http://127.0.0.1:11434")
        self.titles = Titles()
        self.state = {}
        self.lock = threading.Lock()
        from byorzin_monitor.network import install_id
        self.install_id = install_id()
        self._init_recursos(cfg)

    # --- recursos do dia a dia: alertas, histórico, LLM local, detalhes (ver docs/recursos.md)
    def _init_recursos(self, cfg):
        from byorzin_monitor.alerts import Alerts
        from byorzin_monitor.details import SessionLog
        from byorzin_monitor.history import History
        from byorzin_monitor.ollama import LlmWatcher
        from byorzin_monitor.settings import Settings
        self.settings = Settings()
        self.alerts = Alerts(cfg["hostname"], self.settings.get, label=self._label)
        self.history = History()
        self.slog = SessionLog()
        self.llm = LlmWatcher(cfg.get("ollama_url") or "http://127.0.0.1:11434")
        self.events.listeners += [self.alerts.on_event, self.history.on_event, self.slog.on_event]

    def _label(self, sid):
        info = read_json(SESSION_INFO_DIR / f"{sid}.json", {}) or {}
        return info.get("title") or self.titles.get(sid)

    def _tick_recursos(self):
        sett = self.settings.get()
        if sett.get("llm_session", True):
            self.llm.poll((self.host.data.get("gpu") or {}).get("util"), sett.get("llm_gpu_pct", 30))
        self.history.sync_tokens(self.tokens)
        self.history.save()

    def session_detail(self, sid):
        with self.lock:
            s = next((x for x in self.state.get("sessions", []) if x["id"] == sid), None)
        if s is None:
            return None
        return {"host": self.cfg["hostname"], "install_id": self.install_id, "session": s, "events": self.slog.get(sid),
                "first_event": self.slog.first.get(sid)}

    def week_start(self, rate):
        ra = ((rate or {}).get("seven_day") or {}).get("resets_at")
        if ra:
            ra = float(ra)
            while ra < time.time():      # snapshot antigo: avança para a janela atual
                ra += 7 * 86400
            return ra - 7 * 86400
        now = datetime.now()
        monday = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() - now.weekday() * 86400
        return monday

    def _reload(self):
        if self.live is None:
            return
        h = self.live.get().get("hostname")
        if h and h != self.cfg["hostname"]:
            log(f"nome da máquina mudou: {self.cfg['hostname']} -> {h}")
            self.cfg["hostname"] = h
            self.alerts.host = h

    def build(self):
        self._reload()
        now = time.time()
        self.events.poll()
        live = read_sessions()
        acc = identify_account()
        rates = {}
        for aid, r in rate_accounts(read_json(RATE_FILE), acc["id"]).items():
            # outra conta que já passou por esta máquina: só enquanto é recente
            if aid != acc["id"] and now - (r.get("seen_at") or 0) > ACCOUNT_STALE:
                continue
            r = dict(r)
            for k in ("seven_day", "five_hour"):   # janela que já renovou não vale mais
                w = r.get(k)
                if isinstance(w, dict) and w.get("resets_at") and float(w["resets_at"]) < now:
                    r[k] = {"pct": 0.0, "resets_at": None, "renewed": True}
            rates[aid] = r
        rate = rates.get(acc["id"])     # campo antigo: a conta desta máquina (coletores antigos leem só ele)
        sessions = []
        for sid, base in sorted(live.items(), key=lambda kv: kv[1]["since"]):
            ev = self.events.sess.get(sid, {})
            info = read_json(SESSION_INFO_DIR / f"{sid}.json", {}) or {}
            subs = [{"id": aid, "type": s.get("type"), "tool": s.get("tool"), "waiting": bool(s.get("waiting"))}
                    for aid, s in ev.get("subagents", {}).items() if now - s.get("last", 0) < SUBAGENT_STALE]
            mood = ev.get("mood") if ev.get("mood_until", 0) > now else None
            status = ev.get("status", "idle")
            if status == "idle" and subs:        # turno acabou, mas os agentes seguem trabalhando
                status = "waiting" if any(x["waiting"] for x in subs) else "working"
            sessions.append({**base, "status": status, "tool": ev.get("tool") if status == ev.get("status") else None,
                             "mood": mood, "subagents": subs, "last": ev.get("last", 0),
                             "tokens": self.tokens.sessions.get(sid, 0),
                             "model": info.get("model"), "title": info.get("title") or self.titles.get(sid),
                             "context_pct": info.get("context_pct"),
                             "cost_usd": info.get("cost_usd"),
                             "account": info["account"] if valid_account(info.get("account")) else acc["id"]})
            self.events.last_activity = max(self.events.last_activity, base["since"])
        if self.settings.get().get("llm_session", True):
            sessions += self.llm.sessions(self.settings.get().get("llm_linger_seconds", 60))
        ws = self.week_start(rate)
        st = {"host": self.cfg["hostname"], "install_id": self.install_id, "ts": now, "sessions": sessions, "rate": rate,
              "account": acc, "rates": rates,
              "tokens": self.tokens.summary(ws), "week_start": ws,
              "last_activity": self.events.last_activity, "events_recent": self.events.recent[-25:],
              "host_metrics": self.host.data, "stats": self._stats(), "alerts": self.alerts.recent()}
        with self.lock:
            self.state = st

    def _stats(self):
        sc = read_json(CLAUDE_DIR / "stats-cache.json", {}) or {}
        days = sc.get("dailyActivity") or []
        if not days:
            return {}
        top = max(days, key=lambda d: d.get("messageCount", 0))
        return {"record_messages": {"date": top.get("date"), "messages": top.get("messageCount"),
                                    "tools": top.get("toolCallCount")},
                "days_active": len(days),
                "total_messages": sum(d.get("messageCount", 0) for d in days)}

    def loop(self):
        last_tok = last_host = 0
        while True:
            t = time.time()
            try:
                if t - last_tok > 30:
                    self.tokens.scan()
                    last_tok = t
                if t - last_host > 10:
                    self.host.collect()
                    last_host = t
                self._tick_recursos()
                self.build()
            except Exception as e:
                log("erro no ciclo:", repr(e))
            time.sleep(1.5)


def make_handler(col, token):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            path, _, query = self.path.partition("?")
            if path not in ("/state", "/history", "/session"):
                self.send_error(404)
                return
            tok = token() if callable(token) else token     # callable: relido do config.toml
            if tok and not hmac.compare_digest(self.headers.get("Authorization") or "", f"Bearer {tok}"):
                self.send_error(401)
                return
            if path == "/history":
                q = parse_qs(query)
                try:
                    n = int(q.get("days", ["30"])[0])
                except ValueError:
                    n = 30
                data = {"host": col.cfg["hostname"], "install_id": col.install_id, "days": col.history.export(n)}
            elif path == "/session":
                data = col.session_detail(parse_qs(query).get("id", [""])[0])
                if data is None:
                    self.send_error(404)
                    return
            else:
                with col.lock:
                    data = col.state
            # served_at: relógio do coletor no momento da resposta (o display usa para corrigir
            # diferença de relógio; "ts" pode estar alguns segundos atrasado pelo ciclo do coletor)
            data = {**data, "served_at": round(time.time(), 3)}
            with col.lock:
                body = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    return H


class PortInUse(RuntimeError):
    pass


def bind_server(bind, port, handler, what):
    """Abre o servidor HTTP; porta ocupada vira uma mensagem clara (PortInUse), sem traceback."""
    import errno
    try:
        return ThreadingHTTPServer((bind, int(port)), handler)
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            raise PortInUse(f"a porta {port} ({what}) já está em uso em {bind}: outro byorzin-monitor já está "
                            f"rodando (systemctl --user status byorzin-monitor-*) ou outro programa usa a porta. "
                            f"Troque `{'port' if what == 'coletor' else 'panel_port'}` no config.toml ou pare o outro.") from None
        if e.errno == errno.EADDRNOTAVAIL:
            raise PortInUse(f"endereço {bind} não existe nesta máquina (bind no config.toml)") from None
        raise


def main():
    cfg = load_config()
    ensure_state_dir()
    # [máquinas] token relido sem reiniciar (pareamento) + anúncio na rede local
    from byorzin_monitor.network import Announcer, LiveConfig
    live = LiveConfig()
    col = Collector(cfg, live)
    # abre a porta antes da leitura inicial (que pode demorar): porta ocupada falha na hora
    srv = bind_server(cfg["bind"], cfg["port"], make_handler(col, live.token), "coletor")
    log("lendo transcripts (primeira vez pode demorar)...")
    col.tokens.scan()
    col.host.collect()
    col.build()
    threading.Thread(target=col.loop, daemon=True).start()
    if not cfg["token"]:
        log("AVISO: sem token no config.toml — /state aberto para quem alcançar a porta")
    Announcer(live).start()
    log(f"coletor {cfg['hostname']} em {cfg['bind']}:{cfg['port']}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
