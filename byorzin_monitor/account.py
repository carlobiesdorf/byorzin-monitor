# Conta do Claude logada nesta máquina (várias contas: ver docs/maquinas.md, "Várias contas").
# A fonte é o .claude.json do Claude Code (oauthAccount). Pela rede só saem um id derivado
# (12 hex de sha256) e um rótulo curto; e-mail, nome completo e o uuid cru nunca saem daqui.
import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path

from byorzin_monitor.common import STATE_DIR, read_json, write_json_atomic

API = {"id": "api", "label": "API key"}      # sem oauthAccount: chave de API (sem limites de uso)
ID_RE = re.compile(r"^(?:[0-9a-f]{12}|api)$")
LABEL_MAX = 24
CACHE_FILE = STATE_DIR / "account.json"      # cache entre processos (a status line roda a cada atualização)
TEAM_TYPES = ("team", "enterprise")


def claude_json_paths():
    """Onde o Claude Code guarda a conta: $CLAUDE_CONFIG_DIR/.claude.json (se definido) e ~/.claude.json."""
    out = []
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env:
        out.append(Path(env) / ".claude.json")
    out.append(Path.home() / ".claude.json")
    return out


def claude_json():
    """O primeiro .claude.json que existe (prefere o do CLAUDE_CONFIG_DIR), ou None."""
    for p in claude_json_paths():
        if p.is_file():
            return p
    return None


def valid_id(x):
    return isinstance(x, str) and bool(ID_RE.match(x))


def clean_label(s):
    """Rótulo de conta: texto curto, sem caracteres de controle; None se não sobrar nada."""
    if not isinstance(s, str):
        return None
    s = "".join(" " if unicodedata.category(c)[0] in "CZ" else c for c in s)
    s = " ".join(s.split())[:LABEL_MAX].strip()
    return s or None


def account_id(oa):
    """Id público: 12 hex de sha256(accountUuid:organizationUuid). A mesma pessoa em outra
    organização (ex.: pessoal e equipe) tem limites separados, então é outra conta."""
    raw = f"{oa.get('accountUuid')}:{oa.get('organizationUuid') or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def default_label(oa, aid):
    """Rótulo padrão, nunca sensível: nome da organização de equipe; senão o primeiro nome;
    senão conta-<4 hex>. Nada com @ (a organização pessoal se chama "<e-mail>'s Organization")."""
    otype = str(oa.get("organizationType") or "").lower()
    org = oa.get("organizationName")
    if any(t in otype for t in TEAM_TYPES) and isinstance(org, str) and "@" not in org:
        lab = clean_label(org)
        if lab:
            return lab
    name = oa.get("displayName")
    if isinstance(name, str) and "@" not in name:
        first = clean_label((name.split() or [""])[0])
        if first:
            return first
    return f"conta-{aid[:4]}"


def parse(data):
    """{id, label} a partir do conteúdo do .claude.json."""
    oa = data.get("oauthAccount") if isinstance(data, dict) else None
    if not isinstance(oa, dict) or not isinstance(oa.get("accountUuid"), str) or not oa["accountUuid"]:
        return dict(API)
    aid = account_id(oa)
    return {"id": aid, "label": default_label(oa, aid)}


def _sig(p):
    st = p.stat()
    return [str(p), st.st_mtime_ns, st.st_size]


_MEM = {"sig": None, "acc": None}


def identify():
    """Conta desta máquina agora, com cache pelo mtime do .claude.json (na memória e em disco)."""
    p = claude_json()
    if p is None:
        return dict(API)
    try:
        sig = _sig(p)
    except OSError:
        return dict(API)
    if _MEM["sig"] == sig:
        return dict(_MEM["acc"])
    c = read_json(CACHE_FILE)
    if isinstance(c, dict) and c.get("sig") == sig and valid_id(c.get("id")) and isinstance(c.get("label"), str):
        acc = {"id": c["id"], "label": c["label"]}
    else:
        try:
            with open(p, encoding="utf-8") as f:
                acc = parse(json.load(f))
        except (OSError, ValueError):
            acc = dict(API)       # arquivo ilegível no meio de uma gravação: tenta de novo na próxima
            return acc
        try:
            write_json_atomic(CACHE_FILE, {"sig": sig, **acc})
        except OSError:
            pass
    _MEM.update(sig=sig, acc=acc)
    return dict(acc)


# ---------------------------------------------------------------- rate.json por conta
def rate_accounts(raw, current_id):
    """Conteúdo de rate.json -> {id: snapshot}. Formato antigo (um snapshot só, sem conta) vira
    o snapshot da conta atual desta máquina."""
    if not isinstance(raw, dict):
        return {}
    if isinstance(raw.get("accounts"), dict):
        return {k: v for k, v in raw["accounts"].items() if valid_id(k) and isinstance(v, dict)}
    if raw.get("seven_day") or raw.get("five_hour"):
        return {current_id: raw}
    return {}
