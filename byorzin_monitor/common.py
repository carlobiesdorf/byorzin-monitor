# Caminhos, configuração e utilitários compartilhados (só biblioteca padrão)
import json
import os
import socket
import sys
import tomllib
from pathlib import Path

HOME = Path.home()
CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", HOME / ".claude"))
APP = "byorzin-monitor"
if sys.platform == "darwin":
    # macOS: pasta padrão do sistema; XDG_* (se definidas) continuam valendo, como nos testes
    _MAC = HOME / "Library" / "Application Support"
    STATE_DIR = Path(os.environ["XDG_STATE_HOME"]) / APP if os.environ.get("XDG_STATE_HOME") else _MAC / APP / "state"
    CONFIG_DIR = Path(os.environ["XDG_CONFIG_HOME"]) / APP if os.environ.get("XDG_CONFIG_HOME") else _MAC / APP
else:
    STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", HOME / ".local/state")) / APP
    CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / APP
CONFIG_FILE = CONFIG_DIR / "config.toml"
# nomes da versão anterior (claude-monitor), usados só na migração
LEGACY_STATE_DIR = STATE_DIR.parent / "claude-monitor"
LEGACY_CONFIG_DIR = CONFIG_DIR.parent / "claude-monitor"

EVENTS_FILE = STATE_DIR / "events.jsonl"
RATE_FILE = STATE_DIR / "rate.json"
SESSION_INFO_DIR = STATE_DIR / "statusline"   # um arquivo por sessão (modelo, contexto, custo)
TOKENS_FILE = STATE_DIR / "tokens.json"

DEFAULTS = {
    "port": 8787,
    "bind": "0.0.0.0",
    "token": "",
    "peers": [],                 # ex.: ["http://192.168.1.10:8787"]
    # macOS devolve "MacBook-Pro.local"; o ".local" só ocupa espaço na tela
    "hostname": socket.gethostname().removesuffix(".local") if sys.platform == "darwin" else socket.gethostname(),
    "statusline_chain": "",      # comando da status line anterior, se houver
    "panel_port": 8788,
    "backend": "auto",           # tela: auto | turing-a | ... (ver display/backends)
    "device": "",                # porta/dispositivo da tela (vazio = detectar)
    "brightness_day": 60,
    "brightness_night": 12,
    "night_start": 23,
    "night_end": 7,
}


CONFIG_ERROR = None      # mensagem do último erro de leitura do config.toml (doctor mostra)
_warned = set()


def _toml_error_line(err):
    import re
    m = re.search(r"line (\d+)", str(err))
    return int(m.group(1)) if m else None


def _salvage(text):
    """Lê o que der de um config.toml inválido: comenta a linha com erro e tenta de novo."""
    lines = text.splitlines()
    for _ in range(50):
        try:
            return tomllib.loads("\n".join(lines))
        except tomllib.TOMLDecodeError as e:
            n = _toml_error_line(e)
            if not n and "end of document" in str(e):      # erro na última linha
                n = max((i + 1 for i, ln in enumerate(lines) if ln.strip() and not ln.startswith("#")), default=None)
            if not n or n > len(lines) or lines[n - 1].startswith("#!byorzin"):
                return {}
            lines[n - 1] = "#!byorzin " + lines[n - 1]
    return {}


def load_config(strict=False):
    """config.toml + padrões. Arquivo inválido não derruba nada: avisa no stderr (uma vez por
    erro), usa os padrões e o que der para aproveitar do arquivo. strict=True: levanta o erro."""
    global CONFIG_ERROR
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_FILE, "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        CONFIG_ERROR = None
        return cfg
    except OSError as e:
        CONFIG_ERROR = f"não consegui ler {CONFIG_FILE}: {e}"
        if strict:
            raise
        return cfg
    try:
        text = raw.decode("utf-8")
        cfg.update(tomllib.loads(text))
        CONFIG_ERROR = None
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        if strict:
            raise
        n = _toml_error_line(e)
        CONFIG_ERROR = f"config.toml inválido{f' na linha {n}' if n else ''}: {e}"
        if CONFIG_ERROR not in _warned:
            _warned.add(CONFIG_ERROR)
            import sys
            print(f"byorzin-monitor: {CONFIG_FILE}: {CONFIG_ERROR} — usando os padrões no que não deu para ler",
                  file=sys.stderr, flush=True)
        if isinstance(e, tomllib.TOMLDecodeError):
            cfg.update(_salvage(text))
    return cfg


def config_error():
    """Erro da última leitura do config.toml (None se ok). Relê o arquivo."""
    load_config()
    return CONFIG_ERROR


def ensure_state_dir():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_INFO_DIR.mkdir(parents=True, exist_ok=True)


def write_json_atomic(path, data):
    import tempfile
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix="." + path.name)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default
