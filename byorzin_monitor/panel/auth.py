# Acesso ao painel (porta 8788). Modelo:
#   - deste computador (cliente 127.0.0.1/::1 e Host localhost/127.0.0.1): liberado;
#   - de outro aparelho da rede: precisa da CHAVE DO PAINEL, entregue uma vez por um link
#     (http://IP:8788/?key=...). O painel troca a chave por um cookie HttpOnly e tira a chave da URL;
#   - entre máquinas pareadas (/api/sync, /api/peers/*): Bearer com o token do grupo.
# Todo POST também passa pela defesa contra CSRF (JSON + cabeçalho próprio + Origin igual ao Host).
#
# A chave fica em ~/.config/byorzin-monitor/panel_key (600), gerada no primeiro uso. Não é o token
# do grupo: vazar o link do painel não dá acesso aos coletores. Para trocar a chave, apague o
# arquivo (ou use "Gerar nova chave" no painel aberto neste computador).
import hashlib
import hmac
import ipaddress
import os
import secrets
import socket
import threading
from http.cookies import SimpleCookie

from byorzin_monitor.common import CONFIG_DIR

KEY_FILE = CONFIG_DIR / "panel_key"
CSRF_HEADER = "X-Byorzin"
COOKIE_MAX_AGE = 400 * 86400          # o máximo que os navegadores aceitam; o tablet não pede de novo
_lock = threading.Lock()
_cache = {"mtime": None, "key": None}


def _read_key():
    try:
        v = KEY_FILE.read_text().strip()
        return v if len(v) >= 16 else None
    except OSError:
        return None


def panel_key():
    """Chave do painel; cria (600) se não existir. Relida quando o arquivo muda."""
    with _lock:
        try:
            m = KEY_FILE.stat().st_mtime_ns
        except OSError:
            m = None
        if m is not None and m == _cache["mtime"] and _cache["key"]:
            return _cache["key"]
        k = _read_key()
        if not k:
            k = _write_key(secrets.token_urlsafe(24))
        _cache.update(mtime=KEY_FILE.stat().st_mtime_ns, key=k)
        return k


def _write_key(k):
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = KEY_FILE.with_name(".panel_key.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(k + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, KEY_FILE)
    return k


def rotate_key():
    """Gera uma chave nova: links e cookies antigos deixam de valer."""
    with _lock:
        k = _write_key(secrets.token_urlsafe(24))
        _cache.update(mtime=KEY_FILE.stat().st_mtime_ns, key=k)
    return k


def key_ok(candidate):
    return bool(candidate) and hmac.compare_digest(str(candidate).encode(), panel_key().encode())


def cookie_name(port):
    # cookies não separam por porta: o nome leva a porta para dois painéis no mesmo IP não se atropelarem
    return f"byorzin_panel_{int(port)}"


def cookie_value():
    """Derivado da chave (o cookie não carrega a chave em si)."""
    return hmac.new(panel_key().encode(), b"byorzin-panel-cookie-v1", hashlib.sha256).hexdigest()


def cookie_ok(header, port):
    if not header:
        return False
    try:
        c = SimpleCookie()
        c.load(header)
    except Exception:
        return False
    m = c.get(cookie_name(port))
    return bool(m) and hmac.compare_digest(m.value.encode(), cookie_value().encode())


def set_cookie_header(port):
    return (f"{cookie_name(port)}={cookie_value()}; Max-Age={COOKIE_MAX_AGE}; Path=/; HttpOnly; SameSite=Strict")


def bearer_ok(header, token):
    return bool(token) and bool(header) and hmac.compare_digest(str(header).encode(), f"Bearer {token}".encode())


# ---------------------------------------------------------------- endereços
def split_host(host_header):
    """'127.0.0.1:8788' / '[::1]:8788' / 'localhost' -> (nome em minúsculas, porta ou None)."""
    h = (host_header or "").strip().lower()
    if h.startswith("["):
        name, _, rest = h[1:].partition("]")
        port = rest[1:] if rest.startswith(":") else None
        return name, port
    if h.count(":") == 1:
        name, port = h.split(":")
        return name, port
    return h, None


def _loopback(ip):
    try:
        a = ipaddress.ip_address(ip)
        if a.version == 6 and a.ipv4_mapped:
            a = a.ipv4_mapped
        return a.is_loopback
    except ValueError:
        return False


LOCAL_NAMES = {"localhost", "127.0.0.1", "::1"}


def is_local(client_ip, host_header, server_ip=None):
    """Pedido feito neste computador, por um endereço local de verdade (não um domínio que
    resolve para 127.0.0.1: isso seria DNS rebinding e cai na regra da rede)."""
    name, _ = split_host(host_header)
    if _loopback(client_ip):
        return name in LOCAL_NAMES or (name.endswith(".localhost")) or _loopback(name)
    # o navegador desta máquina abrindo o painel pelo IP da rede dela mesma
    if server_ip and client_ip == server_ip and name == str(server_ip).lower():
        return True
    return False


def origin_ok(origin, host_header):
    """Sem Origin (curl, outro painel) passa; com Origin, tem que ser este mesmo endereço."""
    if origin is None:
        return True
    o = origin.strip().lower()
    if not o.startswith("http://") and not o.startswith("https://"):
        return False
    return o.split("://", 1)[1].rstrip("/") == (host_header or "").strip().lower()


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))      # não envia nada; só descobre a interface de saída
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def panel_links(port):
    """Links com a chave para abrir o painel e a /tela em outro aparelho."""
    from urllib.parse import quote
    base = f"http://{lan_ip()}:{int(port)}"
    k = quote(panel_key(), safe="")
    return {"url": f"{base}/?key={k}", "tela": f"{base}/tela?key={k}", "base": base}
