# Várias máquinas: config relida sem reiniciar, peers pareados (machines.json), último estado
# conhecido de cada máquina (seen.json) e descoberta na rede local por UDP broadcast.
# Só biblioteca padrão. O token NUNCA vai nos anúncios de descoberta.
import json
import os
import re
import select
import socket
import tempfile
import threading
import time
import uuid

from byorzin_monitor import __version__
from byorzin_monitor.common import CONFIG_DIR, CONFIG_FILE, STATE_DIR, load_config, read_json, write_json_atomic

MACHINES_FILE = CONFIG_DIR / "machines.json"   # url do coletor -> {id, host, panel, paired_at}
SEEN_FILE = STATE_DIR / "seen.json"            # último estado conhecido de cada máquina
ID_FILE = CONFIG_DIR / "install_id"
APP_TAG = "byorzin-monitor"
ANNOUNCE_EVERY = 10
FOUND_TTL = 45                                 # some da lista "encontradas" se parar de anunciar
_cfg_lock = threading.Lock()


def norm_url(u, default_port=None):
    """'192.168.1.5' / '192.168.1.5:8787' / 'http://x:8787/' -> 'http://x:porta'."""
    u = (u or "").strip().rstrip("/")
    if not u:
        return ""
    if "://" not in u:
        u = "http://" + u
    hostport = u.split("://", 1)[1]
    if default_port and not re.search(r":\d+$", hostport):
        u += f":{default_port}"
    return u


def url_host(u):
    return u.split("://", 1)[-1].rsplit(":", 1)[0].strip("[]")


def install_id():
    """Identificador aleatório desta instalação (não é segredo; só evita confundir máquinas)."""
    try:
        v = ID_FILE.read_text().strip()
        if v:
            return v
    except OSError:
        pass
    v = uuid.uuid4().hex[:16]
    ID_FILE.parent.mkdir(parents=True, exist_ok=True)
    ID_FILE.write_text(v + "\n")
    return v


# ---------------------------------------------------------------- config dinâmica
class LiveConfig:
    """config.toml com releitura por mtime (no máximo a cada `every` s)."""

    def __init__(self, every=2.0):
        self.every = every
        self._mtime = None
        self._checked = 0
        self.cfg = load_config()
        self._stamp()

    def _stamp(self):
        try:
            self._mtime = os.stat(CONFIG_FILE).st_mtime_ns
        except FileNotFoundError:
            self._mtime = None

    def changed(self):
        """Devolve a config nova se o arquivo mudou desde a última leitura; senão None."""
        now = time.monotonic()
        if now - self._checked < self.every:
            return None
        self._checked = now
        try:
            m = os.stat(CONFIG_FILE).st_mtime_ns
        except FileNotFoundError:
            return None
        if m == self._mtime:
            return None
        self._mtime = m
        try:
            self.cfg = load_config(strict=True)
        except Exception:        # arquivo pela metade/ inválido: fica com o anterior
            return None
        return self.cfg

    def get(self):
        self.changed()
        return self.cfg

    def token(self):
        return self.get().get("token", "")


_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def _toml_str(v):
    out = ['"']
    for ch in str(v):
        o = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif o < 0x20 or o == 0x7F:
            out.append(f"\\u{o:04X}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _toml_key(k):
    k = str(k)
    return k if _BARE_KEY.match(k) else _toml_str(k)


def _toml_value(v):
    import datetime as _dt
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v != v:
            return "nan"
        if v in (float("inf"), float("-inf")):
            return "inf" if v > 0 else "-inf"
        return repr(v)
    if isinstance(v, (_dt.datetime, _dt.date, _dt.time)):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{_toml_key(k)} = {_toml_value(x)}" for k, x in v.items()) + "}"
    return _toml_str(v)


def _is_table_array(v):
    return isinstance(v, list) and v and all(isinstance(x, dict) for x in v)


def toml_dumps(data, _prefix=()):
    """Serializador TOML mínimo (o que o tomllib lê de volta igual): valores simples primeiro,
    depois as tabelas [x] e as listas de tabelas [[x]]."""
    lines, tables = [], []
    for k, v in data.items():
        if isinstance(v, dict) or _is_table_array(v):
            tables.append((k, v))
        else:
            lines.append(f"{_toml_key(k)} = {_toml_value(v)}")
    for k, v in tables:
        path = _prefix + (k,)
        name = ".".join(_toml_key(x) for x in path)
        if isinstance(v, dict):
            body = toml_dumps(v, path)
            if lines:
                lines.append("")
            lines.append(f"[{name}]")
            if body:
                lines.append(body)
        else:
            for item in v:
                if lines:
                    lines.append("")
                lines.append(f"[[{name}]]")
                body = toml_dumps(item, path)
                if body:
                    lines.append(body)
    return "\n".join(lines)


CONFIG_HEADER = ("# Byorzin Monitor — gravado pelo byorzin-monitor (pareamento, setup...).\n"
                 "# Pode editar à mão, mas comentários se perdem quando o programa regrava o arquivo.\n")


def set_config(**changes):
    """Atualiza chaves de topo do config.toml preservando as demais chaves e seções.
    O arquivo é relido com tomllib e regravado inteiro: o bloco de comentários do topo fica, os
    comentários no meio do arquivo se perdem. Valor None remove a chave.
    Se o arquivo atual for inválido, não grava nada e levanta ValueError (para não perder dados)."""
    import tomllib
    with _cfg_lock:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        head = CONFIG_HEADER
        try:
            with open(CONFIG_FILE, "rb") as f:
                raw = f.read()
            data = tomllib.loads(raw.decode("utf-8"))
            # o bloco de comentários do topo do arquivo é mantido; os do meio se perdem
            top = []
            for ln in raw.decode("utf-8").splitlines():
                if ln.strip() and not ln.lstrip().startswith("#"):
                    break
                top.append(ln)
            while top and not top[-1].strip():
                top.pop()
            if top:
                head = "\n".join(top) + "\n"
        except FileNotFoundError:
            data = {}
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
            raise ValueError(f"{CONFIG_FILE} inválido ({e}); corrija o arquivo antes") from e
        for k, v in changes.items():
            if v is None:
                data.pop(k, None)
            else:
                data[k] = v
        text = head + toml_dumps(data) + "\n"
        tomllib.loads(text)          # garantia: o que vai ser gravado é TOML válido
        fd, tmp = tempfile.mkstemp(dir=CONFIG_FILE.parent, prefix=".config.toml")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, CONFIG_FILE)


# ---------------------------------------------------------------- máquinas pareadas
def machines_meta():
    d = read_json(MACHINES_FILE, {}) or {}
    return d if isinstance(d, dict) else {}


def add_peer(url, host="", mid="", panel=""):
    url = norm_url(url, 8787)
    cfg = load_config()
    peers = [norm_url(p) for p in cfg.get("peers", [])]
    if url not in peers:
        set_config(peers=peers + [url])
    meta = machines_meta()
    old = meta.get(url, {})
    meta[url] = {"id": mid or old.get("id", ""), "host": host or old.get("host", ""),
                 "panel": panel or old.get("panel", ""), "paired_at": old.get("paired_at") or time.time()}
    write_json_atomic(MACHINES_FILE, meta)
    return url


def remove_peer(url=None, mid=None):
    """Remove por url e/ou id de instalação. Devolve as urls removidas."""
    meta = machines_meta()
    url = norm_url(url) if url else None
    gone = {u for u, m in meta.items() if (mid and m.get("id") == mid)}
    if url:
        gone.add(url)
    cfg = load_config()
    peers = [norm_url(p) for p in cfg.get("peers", [])]
    left = [p for p in peers if p not in gone]
    if left != peers:
        set_config(peers=left)
    for u in gone:
        meta.pop(u, None)
    write_json_atomic(MACHINES_FILE, meta)
    return sorted(gone & set(peers)) or sorted(gone)


def panel_of(url, cfg=None):
    """Endereço do painel de um peer: o informado no pareamento ou, sem isso, mesmo IP + porta padrão."""
    m = machines_meta().get(norm_url(url), {})
    if m.get("panel"):
        return m["panel"]
    port = (cfg or {}).get("panel_port", 8788)
    return f"http://{url_host(url)}:{port}"


# ---------------------------------------------------------------- último estado conhecido
def load_seen():
    d = read_json(SEEN_FILE, {}) or {}
    return d if isinstance(d, dict) else {}


def save_seen(last_ok, names):
    """Guarda só o necessário para mostrar a máquina offline (sem eventos)."""
    out = {}
    for u, (t, st) in last_ok.items():
        if not st:
            continue
        keep = {k: st.get(k) for k in ("host", "install_id", "ts", "sessions", "host_metrics") if k in st}
        out[u] = {"seen": t, "name": names.get(u, st.get("host")), "state": keep}
    try:
        write_json_atomic(SEEN_FILE, out)
    except OSError:
        pass


# ---------------------------------------------------------------- descoberta (UDP)
def _udp_listen(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):          # várias peças na mesma máquina ouvem a mesma porta
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    s.bind(("", port))
    return s


def _udp_send():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    return s


def disc_params(cfg):
    return (bool(cfg.get("discovery", True)), int(cfg.get("discovery_port", 8789)),
            cfg.get("discovery_address", "255.255.255.255"))


class Announcer(threading.Thread):
    """Roda no coletor: anuncia esta máquina a cada ANNOUNCE_EVERY s e responde a perguntas
    ("quem está aí?") na hora, para o painel/CLI não esperarem o próximo anúncio."""

    def __init__(self, live):
        super().__init__(daemon=True)
        self.live = live
        self.mid = install_id()
        self.stop_ev = threading.Event()

    def message(self):
        cfg = self.live.get()
        return json.dumps({"app": APP_TAG, "v": 1, "id": self.mid, "host": cfg.get("hostname"),
                           "version": __version__, "port": int(cfg.get("port", 8787)),
                           "panel_port": int(cfg.get("panel_port", 8788))}).encode()

    def run(self):
        on, port, addr = disc_params(self.live.get())
        if not on:
            return
        try:
            rx = _udp_listen(port)
        except OSError:
            rx = None
        tx = _udp_send()
        nxt = 0
        while not self.stop_ev.is_set():
            now = time.monotonic()
            if now >= nxt:
                try:
                    tx.sendto(self.message(), (addr, port))
                except OSError:
                    pass              # sem rede no momento
                nxt = now + ANNOUNCE_EVERY
            if rx is None:
                self.stop_ev.wait(min(1.0, nxt - now))
                continue
            r, _, _ = select.select([rx], [], [], max(0.05, min(1.0, nxt - now)))
            if r:
                try:
                    data, src = rx.recvfrom(2048)
                    q = json.loads(data)
                except (OSError, ValueError):
                    continue
                if isinstance(q, dict) and q.get("app") == APP_TAG and q.get("q"):
                    try:
                        tx.sendto(self.message(), src)
                    except OSError:
                        pass
        for s in (rx, tx):
            if s:
                s.close()

    def stop(self):
        self.stop_ev.set()


class Listener(threading.Thread):
    """Roda no painel (e na CLI): coleta os anúncios de outras máquinas."""

    def __init__(self, port=8789, addr="255.255.255.255", own_id=None):
        super().__init__(daemon=True)
        self.port, self.addr = port, addr
        self.own_id = own_id
        self.found = {}             # id -> anúncio + ip + seen
        self.lock = threading.Lock()
        self.stop_ev = threading.Event()
        self.ok = False             # conseguiu abrir a porta

    def ask(self, q):
        try:
            q.sendto(json.dumps({"app": APP_TAG, "q": 1}).encode(), (self.addr, self.port))
        except OSError:
            pass

    def _take(self, data, src):
        try:
            m = json.loads(data)
        except ValueError:
            return
        if not isinstance(m, dict) or m.get("app") != APP_TAG or m.get("q") or not m.get("id"):
            return
        if m["id"] == self.own_id:
            return
        try:
            m = {"id": str(m["id"])[:40], "host": str(m.get("host") or "?")[:64], "version": str(m.get("version") or "")[:20],
                 "port": int(m.get("port") or 8787), "panel_port": int(m.get("panel_port") or 8788)}
        except (TypeError, ValueError):
            return
        m.update(ip=src[0], seen=time.time())
        with self.lock:
            self.found[m["id"]] = m

    def run(self):
        try:
            rx = _udp_listen(self.port)
            self.ok = True
        except OSError:
            rx = None
        q = _udp_send()
        q.bind(("", 0))
        self.ask(q)
        last_ask = time.monotonic()
        socks = [s for s in (rx, q) if s]
        while not self.stop_ev.is_set():
            r, _, _ = select.select(socks, [], [], 1.0)
            for s in r:
                try:
                    data, src = s.recvfrom(2048)
                except OSError:
                    continue
                self._take(data, src)
            if time.monotonic() - last_ask > 60:      # pergunta de novo de tempos em tempos
                self.ask(q)
                last_ask = time.monotonic()
        for s in socks:
            s.close()

    def stop(self):
        self.stop_ev.set()

    def items(self):
        now = time.time()
        with self.lock:
            for k in [k for k, m in self.found.items() if now - m["seen"] > FOUND_TTL]:
                self.found.pop(k)
            return sorted(self.found.values(), key=lambda m: (m["host"], m["ip"]))


def discover(seconds=3.0, cfg=None):
    """Ouve a rede por alguns segundos (CLI/doctor). Inclui esta máquina (marcada como own)."""
    cfg = cfg or load_config()
    _, port, addr = disc_params(cfg)
    ls = Listener(port, addr, own_id=None)
    ls.start()
    time.sleep(seconds)
    ls.stop()
    own = install_id()
    out = ls.items()
    for m in out:
        m["own"] = m["id"] == own
    return out, ls.ok


def is_paired(found, cfg, meta=None):
    """Um anúncio corresponde a algum peer já configurado?"""
    meta = machines_meta() if meta is None else meta
    peers = {norm_url(p) for p in cfg.get("peers", [])}
    if any(m.get("id") == found["id"] for u, m in meta.items() if u in peers):
        return True
    return f"http://{found['ip']}:{found['port']}" in peers
