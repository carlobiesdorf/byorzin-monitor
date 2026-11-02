# Idioma dos textos desenhados na tela (cenas e layouts). O texto-fonte é o pt-BR; para inglês,
# T() procura a tradução em EN. O idioma vem do ajuste `language` (display.json) e é aplicado a
# cada quadro por set_lang(). Sem tradução cadastrada, o texto sai em pt-BR.
LANG = "pt-BR"
LANGS = ["pt-BR", "en"]


def set_lang(lang):
    global LANG
    LANG = "en" if str(lang or "").lower().startswith("en") else "pt-BR"


def is_en():
    return LANG == "en"


def T(_s, **kw):
    out = EN.get(_s, _s) if LANG == "en" else _s
    return out.format(**kw) if kw else out


def dec(s):
    """Separador decimal: vírgula em pt-BR, ponto em inglês."""
    return s if LANG == "en" else s.replace(".", ",")


def plural(n, one, many):
    return T(one if n == 1 else many, n=n)


DAYS = {"pt-BR": ("seg", "ter", "qua", "qui", "sex", "sáb", "dom"),
        "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")}


def day_name(weekday):
    return DAYS[LANG][weekday]


def day_month(date_iso):
    """'2026-10-14' -> '14/10' (pt-BR) ou '10/14' (en)."""
    d, m = date_iso[8:10], date_iso[5:7]
    return f"{m}/{d}" if LANG == "en" else f"{d}/{m}"


EN = {
    # rodapés e barra de cima
    "SEMANA": "WEEK",
    "aguardando a 1ª resposta da status line": "waiting for the first status line update",
    "renova {when}  (em {dur})": "resets {when}  (in {dur})",
    " · visto há {dur}": " · seen {dur} ago",
    "hoje {x}": "today {x}",
    "semana {x}": "week {x}",
    " · renova {when}": " · resets {when}",
    "hoje {a} · semana {b}": "today {a} · week {b}",
    # status das sessões
    "Agente": "Agent",
    "pronto!": "done!",
    "limite!": "limit!",
    "erro": "error",
    "esperando você": "waiting for you",
    "gerando · {d}": "generating · {d}",
    "{n} agente trabalhando · {d}": "{n} agent working · {d}",
    "{n} agentes trabalhando · {d}": "{n} agents working · {d}",
    "pensando": "thinking",
    "ocioso há {d}": "idle for {d}",
    # cenas
    "sem sessões há {d}": "no sessions for {d}",
    "sonhando com...": "dreaming of...",
    "nova sessão": "new session",
    "não aguenta": "can't take",
    "mais tokens!": "more tokens!",
    "5h em {p}%": "5h at {p}%",
    "renova {t}": "resets {t}",
    "(em {d})": "(in {d})",
    "semana em {p}%": "week at {p}%",
    "{n} núcleos": "{n} cores",
    "nenhum modelo carregado": "no model loaded",
    "{n} rodando": "{n} running",
    " · {n} parados": " · {n} stopped",
    "com problema: ": "unhealthy: ",
    "terminou!": "finished!",
    "sessão": "session",
    "trabalhou {d}": "worked {d}",
    # ritmo e sonhos
    "ritmo: ok": "pace: ok",
    "~{p}% no fim": "~{p}% at reset",
    "acaba ~{when}h": "runs out ~{when}h",
    "tokens em {dm}": "tokens on {dm}",
    "recorde do dia!": "daily record!",
    "mensagens em {dm}": "messages on {dm}",
    "{n} ferramentas": "{n} tools",
    "dias usando o Claude": "days using Claude",
    "em {host}": "on {host}",
    "modelo favorito": "favorite model",
    "{x} na semana": "{x} this week",
    "tokens nesta semana": "tokens this week",
    "sonho de teste": "test dream",
    "teste": "test",
    # layouts
    "agente": "agent",
    "geral": "general",
    "sem agentes": "no agents",
    "sessões": "sessions",
    "+{n} sessões": "+{n} sessions",
    " · {n} ativas": " · {n} active",
    " ociosas": " idle",
    "contexto": "context",
    "{n} agente": "{n} agent",
    "{n} agentes": "{n} agents",
    "+{n} agentes": "+{n} agents",
    "única sessão aberta": "only open session",
    "precisa de você!": "needs you!",
    "pensando…": "thinking…",
    " +{n} agentes": " +{n} agents",
    "agente · ": "agent · ",
    "nova mensagem": "new message",
    "agente {t} começou": "agent {t} started",
    "agente {t} terminou": "agent {t} finished",
    "terminou ✓": "finished ✓",
    "falhou: {e}": "failed: {e}",
    "{tool} falhou": "{tool} failed",
    "pediu permissão": "asked permission",
    "permissão negada": "permission denied",
    "aviso": "notice",
    "sessão aberta": "session opened",
    "AGORA": "NOW",
    "sem eventos ainda": "no events yet",
    "SESSÕES": "SESSIONS",
    "ativas": "active",
    "AGENTES": "AGENTS",
    "rodando": "running",
    "HOJE": "TODAY",
    "tokens": "tokens",
    "usado": "used",
    "tokens por hora · últimas 24h": "tokens per hour · last 24h",
    "pico {x}": "peak {x}",
    "nenhuma sessão aberta": "no open sessions",
    "nenhuma máquina": "no machines",
    "{n} sessão": "{n} session",
    "{n} sessões": "{n} sessions",
    " · {n} ativa": " · {n} active",
    "offline": "offline",
    "às {t}": "at {t}",
    "nenhuma sessão": "no sessions",
    "sem sessões no último contato": "no sessions at last contact",
    "+{n} máquinas · {up} online · {s} sessões": "+{n} machines · {up} online · {s} sessions",
    "+{n} máquinas · {up} online": "+{n} machines · {up} online",
    # singular/plural e "agora há pouco"
    "+{n} sessão": "+{n} session",
    "+{n} agente": "+{n} agent",
    " +{n} agente": " +{n} agent",
    "{n} ativa": "{n} active",
    "{n} ativas": "{n} active",
    "sem sessões · agora há pouco": "no sessions · just now",
    "ocioso · agora há pouco": "idle · just now",
    "agora há pouco": "just now",
    # várias contas
    "+{n} contas": "+{n} accounts",
    "conta {x}": "account {x}",
}
