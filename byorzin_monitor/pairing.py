# Pareamento por código: a máquina A gera um código de 6 dígitos (5 min); a máquina B o troca,
# pelo painel de A, pelo token comum e pela lista de peers. Ninguém copia token na mão.
#   A: POST /api/pair/code             -> {"code", "expires_at"}   (painel autenticado: local ou link com chave)
#   B: POST A/api/pair/claim {code,..} -> {"token", "peers", ...}   (público, com limite de tentativas)
import hmac
import json
import secrets
import threading
import time
import urllib.error
import urllib.request

from byorzin_monitor import __version__
from byorzin_monitor.common import load_config
from byorzin_monitor.network import (add_peer, install_id, machines_meta, norm_url, panel_of, remove_peer,
                                     set_config, url_host)

CODE_TTL = 300
TRIES_PER_CODE = 5          # errou 5 vezes: o código é invalidado
IP_WINDOW = 300
IP_MAX_FAILS = 10           # por IP, em 5 min
GLOBAL_MAX_FAILS = 30       # de todos os IPs, em 5 min (contra força bruta distribuída)


class PairError(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status = status
        self.msg = msg


class Pairing:
    """Estado do código ativo e contadores de tentativas (em memória, no painel)."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self.code = None
        self.expires = 0
        self.tries = 0
        self.fails = []             # (ts, ip)
        self.lock = threading.Lock()

    def generate(self):
        with self.lock:
            self.code = f"{secrets.randbelow(10 ** 6):06d}"
            self.expires = self.clock() + CODE_TTL
            self.tries = 0
            return {"code": self.code, "expires_at": self.expires, "ttl": CODE_TTL}

    def cancel(self):
        with self.lock:
            self.code = None

    def status(self):
        with self.lock:
            if self.code and self.clock() < self.expires:
                return {"active": True, "expires_at": self.expires}
            return {"active": False}

    def check(self, ip, code):
        """Valida o código; levanta PairError com status HTTP e mensagem clara."""
        with self.lock:
            now = self.clock()
            self.fails = [(t, i) for t, i in self.fails if now - t < IP_WINDOW]
            if sum(1 for _, i in self.fails if i == ip) >= IP_MAX_FAILS or len(self.fails) >= GLOBAL_MAX_FAILS:
                raise PairError(429, "muitas tentativas erradas; aguarde alguns minutos e gere um código novo")
            code = "".join(ch for ch in str(code or "") if ch.isdigit())
            if len(code) != 6:
                raise PairError(400, "o código tem 6 dígitos")
            if not self.code:
                raise PairError(410, "nenhum código ativo nesta máquina; gere um no painel dela")
            if now >= self.expires:
                self.code = None
                raise PairError(410, "código expirado; gere outro")
            if not hmac.compare_digest(code, self.code):
                self.tries += 1
                self.fails.append((now, ip))
                left = TRIES_PER_CODE - self.tries
                if left <= 0:
                    self.code = None
                    raise PairError(403, "código errado; tentativas esgotadas, gere outro código")
                raise PairError(403, f"código errado ({left} tentativa{'s' if left > 1 else ''} restante{'s' if left > 1 else ''})")
            self.code = None           # uso único
            return True


# ---------------------------------------------------------------- lado A (quem gerou o código)
def peer_list(cfg):
    """Peers de A no formato que B entende."""
    meta = machines_meta()
    out = []
    for p in cfg.get("peers", []):
        u = norm_url(p)
        m = meta.get(u, {})
        out.append({"url": u, "panel": panel_of(u, cfg), "host": m.get("host", ""), "id": m.get("id", "")})
    return out


def accept(pairing, ip, body, cfg):
    """Troca o código pelo token. Adiciona B como peer de A. Devolve (resposta, info de B)."""
    pairing.check(ip, body.get("code"))
    try:
        b_port = int(body.get("port") or 8787)
        b_panel = int(body.get("panel_port") or 8788)
    except (TypeError, ValueError):
        raise PairError(400, "porta inválida")
    b = {"url": f"http://{ip}:{b_port}", "panel": f"http://{ip}:{b_panel}",
         "host": str(body.get("host") or "")[:64], "id": str(body.get("id") or "")[:40]}
    others = [p for p in peer_list(cfg) if p["url"] != b["url"] and (not b["id"] or p["id"] != b["id"])]
    token = cfg.get("token") or ""
    if not token:                       # A sem token: cria um agora (o grupo passa a ter um)
        token = secrets.token_hex(18)
        set_config(token=token)
    add_peer(b["url"], b["host"], b["id"], b["panel"])
    resp = {"ok": True, "token": token, "host": cfg.get("hostname"), "id": install_id(),
            "port": int(cfg.get("port", 8787)), "panel_port": int(cfg.get("panel_port", 8788)),
            "version": __version__, "peers": others}
    return resp, b


def tell_peers(others, b, token):
    """Avisa os peers já existentes de A que B entrou no grupo (melhor esforço)."""
    done = []
    for p in others:
        try:
            post(p["panel"] + "/api/peers/add", b, token=token, timeout=3)
            done.append(p["url"])
        except Exception:
            pass
    return done


# ---------------------------------------------------------------- lado B (quem digita o código)
def post(url, body, token=None, timeout=5):
    h = {"Content-Type": "application/json", "X-Byorzin": "1"}      # cabeçalho anti-CSRF do painel
    if token:
        h["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e).get("erro") or str(e)
        except Exception:
            msg = str(e)
        raise PairError(e.code, msg) from None
    except (urllib.error.URLError, OSError) as e:
        raise PairError(502, f"não consegui falar com {url.rsplit('/api', 1)[0]}: {getattr(e, 'reason', e)}") from None


def join(target, code, cfg=None):
    """B: troca o código no painel de A e adota token + peers. Devolve um resumo (sem o token)."""
    cfg = cfg or load_config()
    panel = norm_url(target, 8788)
    me = {"code": code, "id": install_id(), "host": cfg.get("hostname"),
          "port": int(cfg.get("port", 8787)), "panel_port": int(cfg.get("panel_port", 8788))}
    resp = post(panel + "/api/pair/claim", me)
    if not resp.get("ok") or not resp.get("token"):
        raise PairError(502, resp.get("erro") or "resposta inesperada do outro painel")
    a_ip = url_host(panel)
    a_url = f"http://{a_ip}:{int(resp.get('port') or 8787)}"
    a_panel = f"http://{a_ip}:{int(resp.get('panel_port') or 8788)}"
    old_peers = [norm_url(p) for p in cfg.get("peers", [])]
    dropped = []
    if resp["token"] != cfg.get("token"):
        # token novo = grupo novo: peers antigos (com outro token) deixariam de responder
        dropped = [p for p in old_peers if p != a_url]
        for p in dropped:
            remove_peer(p)
        set_config(token=resp["token"])
    add_peer(a_url, resp.get("host", ""), resp.get("id", ""), a_panel)
    for p in resp.get("peers") or []:
        if p.get("id") and p["id"] == me["id"]:
            continue
        add_peer(p["url"], p.get("host", ""), p.get("id", ""), p.get("panel", ""))
    return {"host": resp.get("host"), "url": a_url, "panel": a_panel,
            "peers": [p["url"] for p in resp.get("peers") or [] if p.get("id") != me["id"]], "dropped": dropped}
