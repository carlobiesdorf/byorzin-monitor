# Histórico diário (~90 dias) do coletor: tokens por dia e por modelo, sessões, ferramentas,
# agentes e tempo trabalhando. Fica em STATE_DIR/history.json e sai em GET /history.
# Só metadados: nome da ferramenta e tipo de agente, nunca entradas ou respostas.
import threading
import time
from datetime import datetime, timedelta

from byorzin_monitor.common import STATE_DIR, read_json, write_json_atomic

HISTORY_FILE = STATE_DIR / "history.json"
KEEP_DAYS = 90
GAP_MAX = 15 * 60        # buraco maior que isso entre eventos não conta como trabalho
BUSY = ("UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure", "SubagentStart",
        "SubagentStop", "PermissionDenied")
TOKEN_WINDOW = 8 * 86400   # igual ao do coletor: baldes por hora guardados
STOP = ("Stop", "StopFailure", "SessionEnd", "PermissionRequest")


def day_of(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def _midnight_after(ts):
    d = datetime.fromtimestamp(ts).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return d.timestamp()


def _day_start(day):
    return datetime.strptime(day, "%Y-%m-%d").timestamp()


def tool_key(name):
    """MCP vira 'mcp:servidor' (agrupa as ações de um mesmo servidor)."""
    name = str(name or "?")
    if name.startswith("mcp__"):
        parts = name.split("__")
        return "mcp:" + (parts[1] if len(parts) > 1 else "?")
    return name[:40]


class History:
    def __init__(self, path=HISTORY_FILE, clock=time.time):
        self.path = path
        self.clock = clock
        saved = read_json(path, {}) or {}
        self.days = saved.get("days", {})          # "AAAA-MM-DD" -> agregados
        self.last_ts = saved.get("last_ts", 0)     # maior ts já contado
        self.boot_ts = self.last_ts                # na releitura após reiniciar, só conta o que é mais novo
        self.recent = {}                           # chave do evento -> ts (eventos fora de ordem, ao vivo)
        self.busy = {}                             # sid -> ts do último evento enquanto trabalhava
        self.dirty = False
        self.saved_at = 0
        self.lock = threading.Lock()

    def _d(self, day):
        return self.days.setdefault(day, {"tokens": 0, "models": {}, "sids": [], "tools": {}, "agents": {},
                                          "work_s": 0, "prompts": 0})

    def _add_work(self, a, b):
        """Soma o intervalo [a, b] ao(s) dia(s), dividindo na meia-noite."""
        while a < b:
            cut = min(b, _midnight_after(a))
            d = self._d(day_of(a))
            d["work_s"] = round(d["work_s"] + (cut - a), 1)
            a = cut

    def on_event(self, ev):
        sid, name, ts = ev.get("session_id"), ev.get("hook_event_name"), ev.get("ts") or 0
        # hooks são assíncronos: um evento pode chegar alguns segundos depois de outro mais novo
        key = (sid, name, ts, ev.get("tool_name"), ev.get("agent_id"))
        if not sid or not name or ts <= self.boot_ts or ts < self.last_ts - 300 or key in self.recent:
            return
        with self.lock:
            self.recent[key] = ts
            if len(self.recent) > 5000:
                for k in [k for k, t in self.recent.items() if t < self.last_ts - 300]:
                    del self.recent[k]
            self.last_ts = max(self.last_ts, ts)
            d = self._d(day_of(ts))
            if sid not in d["sids"]:
                d["sids"].append(sid)
            if name == "PreToolUse" and ev.get("tool_name"):
                k = tool_key(ev["tool_name"])
                d["tools"][k] = d["tools"].get(k, 0) + 1
            elif name == "SubagentStart":
                k = str(ev.get("agent_type") or "agente")[:40]
                d["agents"][k] = d["agents"].get(k, 0) + 1
            elif name == "UserPromptSubmit":
                d["prompts"] += 1
            prev = self.busy.get(sid)
            if prev is not None and ts - prev <= GAP_MAX:
                self._add_work(prev, ts)
            if name in BUSY:
                self.busy[sid] = ts
            elif name in STOP or (name == "Notification" and ev.get("notification_type")):
                self.busy.pop(sid, None)
            self.dirty = True

    def sync_tokens(self, tc):
        """Copia do TokenCounter os tokens por dia e por modelo (sem somar: sempre substitui).
        - total do dia: tc.days (soma de tudo que o contador já leu, nunca podado) — vale para hoje,
          para o primeiro dia de uma instalação nova e para os dias antigos;
        - por modelo: baldes por hora (só cobrem TOKEN_WINDOW). Um dia que começou antes do início da
          janela tem baldes faltando (podados), então ali só aumenta, nunca diminui."""
        now = self.clock()
        win_start = now - TOKEN_WINDOW
        per = {}
        for h, b in tc.hours.items():
            p = per.setdefault(day_of(h), {"tokens": 0, "models": {}})
            p["tokens"] += b.get("tot", 0)
            for m, v in (tc.models.get(h) or {}).items():
                p["models"][m] = p["models"].get(m, 0) + v
        cut = day_of(now - KEEP_DAYS * 86400)
        with self.lock:
            for day in set(per) | set(tc.days or {}):
                if day < cut:
                    continue
                p = per.get(day, {"tokens": 0, "models": {}})
                tot = (tc.days or {}).get(day)
                complete = _day_start(day) >= win_start      # todos os baldes do dia ainda existem
                had = day in self.days
                d = self._d(day)
                if tot is None:
                    tot = p["tokens"]
                new_tokens = tot if complete else max(d["tokens"], tot)
                if complete:
                    new_models = p["models"]
                else:
                    new_models = dict(d["models"])
                    for m, v in p["models"].items():
                        new_models[m] = max(new_models.get(m, 0), v)
                if not had or d["tokens"] != new_tokens or d["models"] != new_models:
                    d["tokens"], d["models"] = new_tokens, new_models
                    self.dirty = True

    def prune(self):
        cut = day_of(self.clock() - KEEP_DAYS * 86400)
        with self.lock:
            for day in [k for k in self.days if k < cut]:
                self.days.pop(day)
                self.dirty = True

    def save(self, force=False):
        if not self.dirty or (not force and self.clock() - self.saved_at < 60):
            return
        self.prune()
        with self.lock:
            data = {"days": self.days, "last_ts": self.last_ts}
            self.dirty = False
        write_json_atomic(self.path, data)
        self.saved_at = self.clock()

    def export(self, ndays=30):
        """Últimos `ndays` dias (inclui hoje), sem os ids de sessão: só contagens."""
        ndays = max(1, min(KEEP_DAYS, int(ndays)))
        now = self.clock()
        out = {}
        with self.lock:
            for i in range(ndays):
                day = day_of(now - i * 86400)
                d = self.days.get(day)
                if d:
                    out[day] = {"tokens": d["tokens"], "models": dict(d["models"]), "sessions": len(d["sids"]),
                                "tools": dict(d["tools"]), "agents": dict(d["agents"]),
                                "work_s": round(d["work_s"]), "prompts": d["prompts"]}
        return out
