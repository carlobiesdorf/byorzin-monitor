# Últimos eventos de cada sessão, para o detalhe da sessão no painel (GET /session?id=...).
# Guarda só metadados (evento, ferramenta, tipo de agente), como o events.jsonl.
from collections import deque

PER_SESSION = 20
FIELDS = ("ts", "hook_event_name", "tool_name", "agent_type", "notification_type", "error")


class SessionLog:
    def __init__(self):
        self.ev = {}       # sid -> deque de eventos
        self.first = {}    # sid -> ts do primeiro evento visto

    def on_event(self, ev):
        sid, name = ev.get("session_id"), ev.get("hook_event_name")
        if not sid or not name:
            return
        if name == "SessionEnd":
            self.ev.pop(sid, None)
            self.first.pop(sid, None)
            return
        if name == "PostToolUse":      # o PreToolUse já diz qual ferramenta
            return
        self.first.setdefault(sid, ev.get("ts"))
        r = {k: ev[k] for k in FIELDS if ev.get(k) is not None}
        r["sub"] = bool(ev.get("agent_id"))
        self.ev.setdefault(sid, deque(maxlen=PER_SESSION)).append(r)

    def get(self, sid):
        return list(reversed(self.ev.get(sid, ())))
