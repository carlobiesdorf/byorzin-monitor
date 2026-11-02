# LLM local: vira uma "sessão" especial (kind = "llm") enquanto o Ollama está gerando.
# Heurística (o Ollama não diz "estou gerando"):
#   1. há modelo carregado em /api/ps, e
#   2. o `expires_at` dele mudou desde a última leitura (o Ollama renova o keep-alive a cada
#      requisição), OU a GPU está acima de `llm_gpu_pct`.
#   Cada sinal mantém o estado "gerando" por HOLD segundos.
# Depois de parar, a sessão fica `llm_linger_seconds` como ociosa e some.
# Sem Ollama (conexão recusada), tenta de novo a cada 30 s e não aparece nada.
import json
import time
import urllib.request

POLL = 3
POLL_FAIL = 30
HOLD = 15        # sinal de uso vale como "gerando" por esse tempo (respostas longas não mexem no /api/ps)


class LlmWatcher:
    def __init__(self, url="http://127.0.0.1:11434", clock=time.time):
        self.url = url.rstrip("/")
        self.clock = clock
        self.models = {}        # nome -> {"expires", "since", "last_active", "vram_gb", "active"}
        self.next_poll = 0
        self.ok = False
        self.primed = False     # 1ª leitura: modelo já carregado não conta como "acabou de carregar"

    def fetch(self):
        with urllib.request.urlopen(self.url + "/api/ps", timeout=1) as r:
            return json.load(r).get("models") or []

    def poll(self, gpu_util=None, gpu_pct=30):
        now = self.clock()
        if now < self.next_poll:
            return
        try:
            ms = self.fetch()
            self.ok = True
            self.next_poll = now + POLL
        except Exception:
            self.ok = False
            self.primed = True
            self.models.clear()
            self.next_poll = now + POLL_FAIL
            return
        gpu_busy = gpu_util is not None and gpu_util >= gpu_pct
        seen = set()
        for m in ms:
            name = m.get("name") or m.get("model") or "?"
            seen.add(name)
            exp = m.get("expires_at")
            cur = self.models.get(name)
            if cur is None:     # acabou de carregar: carregar já é sinal de uso
                act = self.primed or gpu_busy
                self.models[name] = {"expires": exp, "since": now, "last_active": now if act else 0,
                                     "active": act, "vram_gb": round((m.get("size_vram") or 0) / 2 ** 30, 1)}
                continue
            changed = exp != cur["expires"]
            cur["expires"] = exp
            signal = changed or gpu_busy
            cur["active"] = signal or now - cur["last_active"] < HOLD
            if signal:
                if now - cur["last_active"] > 300:    # voltou depois de um tempo: conta de novo
                    cur["since"] = now
                cur["last_active"] = now
        for name in [n for n in self.models if n not in seen]:
            self.models.pop(name)
        self.primed = True

    def sessions(self, linger=60):
        now = self.clock()
        out = []
        for name, m in self.models.items():
            if not m["active"] and now - m["last_active"] > linger:
                continue
            out.append({"id": "llm:" + name, "kind": "llm", "project": name, "title": f"LLM local · {name}",
                        "since": m["since"], "status": "working" if m["active"] else "idle", "tool": None,
                        "mood": None, "subagents": [], "last": m["last_active"], "tokens": 0, "model": name,
                        "context_pct": None, "cost_usd": None, "vram_gb": m["vram_gb"]})
        return out
