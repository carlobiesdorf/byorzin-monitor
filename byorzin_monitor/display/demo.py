# Cenário de demonstração para o painel (várias sessões, agentes, alguém esperando você).
# Nomes de máquinas e projetos são fictícios; os títulos seguem o idioma da tela.
import math
import time

from byorzin_monitor import i18n
from byorzin_monitor.display.engine import View

TITLES = {
    "pt-BR": ("Tela USB do monitor", "Assistente de cadastro", "Limite por plano", "Playbook de deploy", "Manual do usuário"),
    "en": ("Monitor USB screen", "Signup wizard", "Per-plan rate limit", "Deploy playbook", "User manual"),
}


# contas fictícias do cenário com várias contas: (id, rótulo pt-BR, rótulo en, semana %, 5h %)
ACCOUNTS = [("a1b2c3d4e5f6", "Trabalho", "Work", 58.0, 31.0), ("0f9e8d7c6b5a", "Pessoal", "Personal", 83.0, 92.0),
            ("c0ffee123456", "Cliente", "Client", 22.0, 5.0), ("5eed5eed5eed", "Estudos", "Study", 40.0, 12.0)]


def _accounts(n, now):
    """[(conta, snapshot)] das n primeiras contas fictícias."""
    out = []
    for i, (aid, pt, en, wk, fh) in enumerate(ACCOUNTS[:n]):
        lab = en if i18n.LANG == "en" else pt
        out.append(({"id": aid, "label": lab},
                    {"seen_at": now, "label": lab, "seven_day": {"pct": wk, "resets_at": now + (2.7 - i * 0.9) * 86400},
                     "five_hour": {"pct": fh, "resets_at": now + (3 - i * 0.7) * 3600}}))
    return out


def demo_view(settings=None, multi_account=False, accounts=None):
    """Cenário de demonstração. Padrão: uma conta só (como a maioria; os testes de imagem dependem
    disso). multi_account=True (ou accounts=N, 2 a 4): o servidor usa a conta "Trabalho", a
    workstation a "Pessoal" e as demais aparecem como contas que também passaram pelo servidor."""
    now = time.time()
    n = accounts or (2 if multi_account else 1)
    t1, t2, t3, t4, t5 = TITLES[i18n.LANG]
    sess_l = [
        {"id": "a", "project": "monitor", "title": t1, "status": "working", "tool": "Bash",
         "since": now - 3 * 3600, "last": now, "tokens": 31e6, "model": "Opus 5.5", "context_pct": 41, "mood": None,
         "subagents": [{"id": "s1", "type": "Explore", "tool": "Grep"}, {"id": "s2", "type": "general-purpose", "tool": "WebFetch"},
                       {"id": "s3", "type": "Explore", "tool": None}]},
        {"id": "b", "project": "web-app", "title": t2, "status": "waiting", "tool": None,
         "since": now - 1500, "last": now - 20, "tokens": 2.2e6, "model": "Opus 5.5", "context_pct": 18, "mood": None,
         "subagents": []},
    ]
    sess_h = [
        {"id": "c", "project": "api", "title": t3, "status": "working", "tool": "Edit",
         "since": now - 2400, "last": now - 2, "tokens": 8.4e6, "model": "Opus 5.5", "context_pct": 63, "mood": None,
         "subagents": [{"id": "s4", "type": "Plan", "tool": "Read"}]},
        {"id": "d", "project": "infra", "title": t4, "status": "idle", "tool": None,
         "since": now - 7200, "last": now - 900, "tokens": 0.6e6, "model": "Sonnet 5.5", "context_pct": 9, "mood": None,
         "subagents": []},
    ]
    ev = [
        (3, "monitor", "PreToolUse", {"tool_name": "Bash"}), (6, "monitor", "PreToolUse", {"tool_name": "Grep", "sub": True}),
        (9, "api", "PreToolUse", {"tool_name": "Edit"}), (20, "web-app", "PermissionRequest", {}),
        (31, "monitor", "SubagentStart", {"agent_type": "Explore"}), (44, "api", "SubagentStart", {"agent_type": "Plan"}),
        (58, "monitor", "PreToolUse", {"tool_name": "WebFetch", "sub": True}), (75, "web-app", "PreToolUse", {"tool_name": "Read"}),
        (130, "infra", "Stop", {}), (200, "monitor", "UserPromptSubmit", {}),
        (260, "api", "PostToolUseFailure", {"tool_name": "Bash"}), (420, "web-app", "SessionStart", {}),
    ]
    events = [{"ts": now - a, "project": p, "hook_event_name": n, **x} for a, p, n, x in ev]
    hourly = [int(4e5 + 3e5 * math.sin(i / 3) ** 2 + (2.5e6 if i in (14, 15, 16, 21, 22) else 0)) for i in range(24)]
    rate = {"seen_at": now, "seven_day": {"pct": 58.0, "resets_at": now + 2.7 * 86400},
            "five_hour": {"pct": 31.0, "resets_at": now + 3 * 3600}}
    base = {"ts": now, "rate": rate, "week_start": now - 4.3 * 86400, "last_activity": now}
    h = {**base, "host": "server", "sessions": sess_h, "events_recent": [e for e in events if e["project"] in ("api", "infra")],
         "tokens": {"today": 2.1e6, "week": 14.8e6, "hourly": hourly, "by_model": {}, "record_day": None},
         "host_metrics": {"cpu": 12, "ram_used_gb": 8.4, "ram_total_gb": 46, "uptime_s": 280000, "cores": 24, "cpu_temp": 49,
                          "gpu": {"name": "RTX 4070 Ti", "util": 34, "mem_used_gb": 9.1, "mem_total_gb": 12, "temp": 61},
                          "ollama": [{"name": "qwen3:14b", "vram_gb": 8.9}],
                          "docker": {"running": 10, "stopped": 10, "problem": []}}}
    c = {**base, "host": "workstation", "sessions": sess_l, "events_recent": [e for e in events if e["project"] in ("monitor", "web-app")],
         "tokens": {"today": 0, "week": 0, "hourly": [0] * 24}}
    # máquina fora do ar: último estado conhecido, "visto há 2 h"
    nb = {"host": "laptop", "ts": now - 7200, "_offline": True, "_seen": now - 7200, "host_metrics": {},
          "sessions": [{"id": "e", "project": "docs", "title": t5, "status": "idle", "tool": None,
                        "since": now - 9000, "last": now - 7300, "tokens": 1.1e6, "subagents": []}]}
    if n >= 2:
        accs = _accounts(min(n, len(ACCOUNTS)), now)
        (wa, wr), (pa, pr) = accs[0], accs[1]
        h.update(account=wa, rate=wr, rates={wa["id"]: wr, **{a["id"]: r for a, r in accs[2:]}})
        c.update(account=pa, rate=pr, rates={pa["id"]: pr})
        for x in sess_h:
            x["account"] = wa["id"]
        for x in sess_l:
            x["account"] = pa["id"]
    return View([("server", h), ("workstation", c), ("laptop", nb)], settings)
