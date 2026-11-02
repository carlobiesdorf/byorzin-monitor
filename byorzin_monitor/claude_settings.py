# Instala/remove os hooks e a status line do Byorzin Monitor no ~/.claude/settings.json.
# Mostra o diff e pede confirmação; faz backup antes de gravar. Idempotente.
# Também reconhece (e substitui) os hooks da versão anterior, "claude-monitor" (cm-hook/cm-statusline).
import difflib
import json
import shutil
import time

from byorzin_monitor.common import CLAUDE_DIR

SETTINGS = CLAUDE_DIR / "settings.json"
EVENTS = ["SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure",
          "PermissionRequest", "Notification", "SubagentStart", "SubagentStop", "Stop", "StopFailure"]


def _ours_hook(cmd):
    cmd = cmd or ""
    return "cm-hook" in cmd or ("byorzin" in cmd and cmd.rstrip().endswith(" hook"))


def _ours_status(cmd):
    cmd = cmd or ""
    return "cm-statusline" in cmd or ("byorzin" in cmd and cmd.rstrip().endswith(" statusline"))


def strip(cfg):
    hooks = cfg.get("hooks", {})
    for ev in list(hooks):
        groups = []
        for g in hooks[ev]:
            g = dict(g, hooks=[h for h in g.get("hooks", []) if not _ours_hook(h.get("command"))])
            if g["hooks"]:
                groups.append(g)
        if groups:
            hooks[ev] = groups
        else:
            hooks.pop(ev)
    if "hooks" in cfg and not hooks:
        cfg.pop("hooks")
    if _ours_status((cfg.get("statusLine") or {}).get("command")):
        cfg.pop("statusLine")
    return cfg


def add(cfg, exe):
    hooks = cfg.setdefault("hooks", {})
    for ev in EVENTS:
        hooks.setdefault(ev, []).append({"hooks": [{"type": "command", "command": f"{exe} hook", "async": True, "timeout": 5}]})
    chain = None
    sl = cfg.get("statusLine")
    if sl and sl.get("command"):
        chain = sl["command"]
    cfg["statusLine"] = {"type": "command", "command": f"{exe} statusline"}
    return cfg, chain


def installed():
    try:
        cfg = json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        return {"hooks": 0, "statusline": False, "legacy": False}
    cmds = [h.get("command") or "" for groups in (cfg.get("hooks") or {}).values() for g in groups for h in g.get("hooks", [])]
    sl = (cfg.get("statusLine") or {}).get("command") or ""
    return {"hooks": sum(1 for c in cmds if _ours_hook(c) and "byorzin" in c),
            "statusline": _ours_status(sl) and "byorzin" in sl,
            "legacy": any("cm-hook" in c for c in cmds) or "cm-statusline" in sl}


def _saved_chain():
    from byorzin_monitor.common import load_config
    c = load_config().get("statusline_chain")
    return c if isinstance(c, str) and c.strip() else None


def apply(exe, remove=False, yes=False, out=print, ask=input):
    """Devolve True se aplicou (ou não havia nada a mudar).
    Ao instalar, a status line que já existia é guardada em `statusline_chain` (config.toml) e
    continua aparecendo (o byorzin-monitor repassa para ela). Ao remover, ela volta para o settings.json."""
    old_txt = SETTINGS.read_text() if SETTINGS.exists() else "{}\n"
    was_ours = _ours_status((json.loads(old_txt).get("statusLine") or {}).get("command"))
    cfg = strip(json.loads(old_txt))
    chain = restore = None
    if not remove:
        cfg, chain = add(cfg, exe)
    else:
        restore = _saved_chain()
        if restore and was_ours and "statusLine" not in cfg:
            cfg["statusLine"] = {"type": "command", "command": restore}
        else:
            restore = None
    new_txt = json.dumps(cfg, indent=2, ensure_ascii=False) + "\n"
    if json.loads(old_txt) == cfg:
        out(f"{SETTINGS}: nada a mudar.")
        return True
    if restore:
        out(f"A status line anterior volta para o settings.json: {restore}")
    out("".join(difflib.unified_diff(old_txt.splitlines(True), new_txt.splitlines(True),
                                     str(SETTINGS), str(SETTINGS) + " (novo)")))
    if chain:
        out(f"\nA status line atual ({chain}) continua aparecendo: o byorzin-monitor repassa para ela.")
    if not yes and ask(f"\nAplicar em {SETTINGS}? [s/N] ").strip().lower() not in ("s", "sim", "y", "yes"):
        out("Nada foi alterado.")
        return False
    if SETTINGS.exists():
        bak = SETTINGS.with_name(f"settings.json.bak-byorzin-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(SETTINGS, bak)
        out(f"backup: {bak}")
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(new_txt)
    from byorzin_monitor.network import set_config
    try:
        if chain:
            set_config(statusline_chain=chain)
        elif restore:
            set_config(statusline_chain=None)       # já voltou para o settings.json
    except ValueError as e:                           # config.toml inválido: avisa, não perde a status line
        out(f"AVISO: não gravei statusline_chain ({e}). Status line anterior: {chain or restore}")
    out("ok. Sessões abertas antes disto passam a enviar eventos na próxima recarga de configuração do Claude Code.")
    return True
