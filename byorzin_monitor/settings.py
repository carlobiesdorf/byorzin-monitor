# Configurações do display, editáveis pelo painel web (cm-panel). Ficam em
# ~/.config/byorzin-monitor/display.json e o display relê sozinho quando o arquivo muda.
import json
import math
import os
import re
import time

from byorzin_monitor.common import CONFIG_FILE, write_json_atomic

SETTINGS_FILE = CONFIG_FILE.parent / "display.json"

LAYOUT_NAMES = ["cards", "lista", "foco", "equipe", "grade", "palco", "atividade", "dashboard", "maquinas"]

# chave: (padrão, tipo, mínimo, máximo)  — mínimo/máximo só para números
SCHEMA = {
    "layout": ("cards", "choice", LAYOUT_NAMES, None),
    "language": ("pt-BR", "choice", ["pt-BR", "en"], None),  # idioma dos textos da tela (cenas e layouts)
    "rotate_layouts": ([], "list", LAYOUT_NAMES, None),     # se tiver 2+, alterna entre eles
    "rotate_seconds": (30, "int", 10, 600),
    "brightness_day": (60, "int", 5, 100),
    "brightness_night": (12, "int", 0, 100),
    "night_start": (23, "int", 0, 23),
    "night_end": (7, "int", 0, 23),
    "night_screen_off": (False, "bool", None, None),        # desliga a tela à noite sem sessões
    "awake_minutes": (5, "int", 1, 120),                    # acordado → sonolento
    "sleep_minutes": (20, "int", 2, 600),                   # sonolento → dormindo
    "dreams": (True, "bool", None, None),
    "dream_every_minutes": (4, "int", 1, 60),
    "host_panel": (True, "bool", None, None),
    "host_panel_every_seconds": (90, "int", 20, 900),
    "wake_animation": (True, "bool", None, None),
    "limit_alert_pct": (90, "int", 50, 100),
    "hide_idle_hours": (24, "int", 0, 720),                 # 0 = mostra todas as ociosas
    "session_name": ("título", "choice", ["título", "projeto"], None),  # título = o da aba do terminal
    "hosts_hidden": ([], "list", None, None),
    "fat_source": ("semana", "choice", ["semana", "5h", "fixo"], None),
    "fps": (5, "int", 1, 8),
    "colors": ({}, "dict", None, None),                     # host -> "#rrggbb" do neon
    "account_labels": ({}, "dict", None, None),             # conta (id) -> rótulo ("Pessoal"); ver account.py
    "force": ({}, "dict", None, None),                      # {"mode": ..., "until": ts} (testes)
    # --- alertas e notificações (ver docs/recursos.md)
    "alert_screen": (True, "bool", None, None),             # moldura amarela pulsando quando alguém espera você
    "alert_screen_seconds": (8, "int", 2, 60),
    "alert_max_brightness": (True, "bool", None, None),     # brilho máximo enquanto o efeito dura
    "alert_idle": (True, "bool", None, None),               # também quando a sessão fica ociosa esperando
    "alert_cooldown_seconds": (90, "int", 10, 3600),        # intervalo mínimo entre avisos da mesma sessão
    "alert_browser": (True, "bool", None, None),            # notificação do navegador no painel
    "alert_sound": (True, "bool", None, None),              # bipe curto no painel (WebAudio)
    "done_minutes": (5, "int", 1, 240),                     # "terminou" só para turnos mais longos que isso
    "done_celebrate": (True, "bool", None, None),
    "ntfy_enabled": (False, "bool", None, None),
    "ntfy_server": ("https://ntfy.sh", "str", None, 200),
    "ntfy_topic": ("", "str", None, 120),
    "ntfy_waiting": (True, "bool", None, None),
    "ntfy_done": (True, "bool", None, None),
    # --- LLM local (Ollama)
    "llm_session": (True, "bool", None, None),
    "llm_gpu_pct": (30, "int", 5, 100),                     # GPU acima disso com modelo carregado = gerando
    "llm_linger_seconds": (60, "int", 0, 900),              # continua na tela por esse tempo depois de parar
}
DEFAULTS = {k: v[0] for k, v in SCHEMA.items()}


COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
TRUE_S = {"true", "1", "on", "yes", "sim"}
FALSE_S = {"false", "0", "off", "no", "não", "nao", ""}


def as_bool(v):
    """bool de verdade a partir de bool, 0/1 ou "true/false/1/0/on/off"; ValueError se não der."""
    if isinstance(v, bool):
        return v
    if isinstance(v, int) and v in (0, 1):
        return bool(v)
    if isinstance(v, str) and v.strip().lower() in TRUE_S | FALSE_S:
        return v.strip().lower() in TRUE_S
    raise ValueError(f"booleano inválido: {v!r}")


def valid_color(c):
    return isinstance(c, str) and bool(COLOR_RE.match(c))


def clean_account_labels(d):
    """{id da conta: rótulo}: só ids válidos e rótulos curtos sem caracteres de controle."""
    from byorzin_monitor.account import clean_label, valid_id
    out = {}
    for k, v in (d.items() if isinstance(d, dict) else ()):
        lab = clean_label(v)
        if valid_id(k) and lab and len(out) < 50:
            out[k] = lab
    return out


def account_label_ok(k, v):
    """Rótulo vindo do painel: id válido, texto de 1 a 24 caracteres, sem controle. "" = apaga."""
    import unicodedata
    from byorzin_monitor.account import LABEL_MAX, valid_id
    if not valid_id(k) or not isinstance(v, str) or len(v.strip()) > LABEL_MAX:
        return False
    return not any(unicodedata.category(c) in ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp") for c in v)


def _num(v, default=0.0):
    try:
        v = float(v)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def validate(data):
    if not isinstance(data, dict):
        data = {}
    out = {}
    for k, (default, typ, lo, hi) in SCHEMA.items():
        v = data.get(k, default)
        try:
            if typ == "int":
                if isinstance(v, bool):
                    raise ValueError
                f = float(v)
                if not math.isfinite(f):
                    raise ValueError
                v = max(lo, min(hi, int(f)))
            elif typ == "bool":
                v = as_bool(v)
            elif typ == "choice":
                v = v if isinstance(v, str) and v in lo else default
            elif typ == "list":
                v = [x[:80] for x in v if isinstance(x, str) and (lo is None or x in lo)][:100] \
                    if isinstance(v, list) else default
            elif typ == "dict":
                v = dict(v) if isinstance(v, dict) else default
            elif typ == "str":
                v = str(v).strip()[:hi] if v is not None else default
        except (TypeError, ValueError, OverflowError):
            v = default
        out[k] = v
    # cor inválida derrubaria o desenho das telas do grupo: só #rrggbb
    out["colors"] = {str(h)[:80]: c.lower() for h, c in out["colors"].items() if valid_color(c)}
    out["account_labels"] = clean_account_labels(out["account_labels"])
    f = out["force"]
    mode = f.get("mode") if isinstance(f, dict) else None
    out["force"] = ({"mode": mode[:40], "until": _num(f.get("until"))}
                    if isinstance(mode, str) and mode else {})
    if out["ntfy_server"] and not re.match(r"^https?://", out["ntfy_server"], re.I):
        out["ntfy_server"] = DEFAULTS["ntfy_server"]
    out["updated_at"] = _num(data.get("updated_at")) or time.time()
    # contador de versão: cada gravação local soma 1; a replicação fica com o maior (desempate: updated_at)
    try:
        out["rev"] = max(0, int(data.get("rev") or 0))
    except (TypeError, ValueError, OverflowError):
        out["rev"] = 0
    return out


class Settings:
    """Lê display.json com cache por mtime (barato de chamar a cada quadro)."""

    def __init__(self):
        self._mtime = None
        self.data = dict(DEFAULTS)

    def get(self):
        try:
            m = os.stat(SETTINGS_FILE).st_mtime
        except FileNotFoundError:
            return self.data
        if m != self._mtime:
            try:
                with open(SETTINGS_FILE) as f:
                    self.data = validate(json.load(f))
                self._mtime = m
            except (OSError, json.JSONDecodeError):
                pass
        return self.data


def load():
    return Settings().get()


def save(data):
    v = validate(data)
    write_json_atomic(SETTINGS_FILE, v)
    return v
