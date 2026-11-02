# Segurança do painel: CSRF, acesso pela rede com a chave do painel, validação de entrada,
# replicação por rev, limite de streams e correção de relógio do detalhe da sessão.
import _isolate
import http.client
import json
import os
import stat
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from byorzin_monitor.common import CONFIG_FILE
from byorzin_monitor import network as net
from byorzin_monitor import settings as SET

TOKEN = "segredo-grupo"


class Recorder(BaseHTTPRequestHandler):
    """Servidor falso: só registra quem chamou (para provar que o token não vazou)."""
    calls = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        Recorder.calls.append((self.path, self.headers.get("Authorization"), self.rfile.read(n)))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    do_GET = do_POST


def make_remote(H, ip="192.0.2.50"):
    class RemoteH(H):
        """Como se o pedido viesse de outro aparelho da rede."""
        def setup(self):
            super().setup()
            self.client_address = (ip, 5555)
    return RemoteH


class PanelSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._cfg_backup = CONFIG_FILE.read_text() if CONFIG_FILE.exists() else None
        cls.fake = ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
        threading.Thread(target=cls.fake.serve_forever, daemon=True).start()
        cls.fake_url = f"http://127.0.0.1:{cls.fake.server_port}"
        cls.write_cfg()
        from byorzin_monitor.panel import server as P
        from byorzin_monitor.panel import auth
        cls.P, cls.auth = P, auth
        P.PANEL = P.Panel()
        cls.local = ThreadingHTTPServer(("127.0.0.1", 0), P.H)
        cls.remote = ThreadingHTTPServer(("127.0.0.1", 0), make_remote(P.H))
        for srv in (cls.local, cls.remote):
            threading.Thread(target=srv.serve_forever, daemon=True).start()

    @classmethod
    def write_cfg(cls, extra=""):
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(f'token = "{TOKEN}"\npeers = []\nhostname = "maq-seg"\nport = {_isolate.free_port()}\n'
                               f'panel_port = {_isolate.free_port()}\ndiscovery = false\n{extra}')
        time.sleep(0.01)

    @classmethod
    def tearDownClass(cls):
        for srv in (cls.local, cls.remote, cls.fake):
            srv.shutdown()
            srv.server_close()
        if cls._cfg_backup is None:
            CONFIG_FILE.unlink(missing_ok=True)
        else:
            CONFIG_FILE.write_text(cls._cfg_backup)

    def setUp(self):
        Recorder.calls.clear()
        self.P.PANEL.live = net.LiveConfig(every=0)

    # ------------------------------------------------ ajudantes
    def req(self, method, path, body=None, headers=None, remote=False, raw=None):
        srv = self.remote if remote else self.local
        c = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=10)
        h = {"Host": f"127.0.0.1:{srv.server_port}"}
        h.update(headers or {})
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        out = r.status, dict(r.getheaders()), r.read()
        c.close()
        return out

    def post(self, path, body, remote=False, headers=None, csrf=True):
        h = {"Content-Type": "application/json"}
        if csrf:
            h["X-Byorzin"] = "1"
        h.update(headers or {})
        return self.req("POST", path, body, h, remote)

    def cookie(self):
        return f"{self.auth.cookie_name(self.remote.server_port)}={self.auth.cookie_value()}"

    # ------------------------------------------------ CSRF
    def test_csrf(self):
        st, _, _ = self.post("/api/settings", {"fps": 4}, csrf=False)
        self.assertEqual(st, 403)
        st, _, _ = self.req("POST", "/api/settings", {"fps": 4}, {"Content-Type": "text/plain", "X-Byorzin": "1"})
        self.assertEqual(st, 403)
        st, _, _ = self.post("/api/settings", {"fps": 4}, headers={"Origin": "http://evil.example"})
        self.assertEqual(st, 403)
        st, _, _ = self.post("/api/pair/code", {}, headers={"Origin": "http://evil.example"})
        self.assertEqual(st, 403)
        port = self.local.server_port
        st, _, _ = self.post("/api/settings", {"fps": 4}, headers={"Origin": f"http://127.0.0.1:{port}"})
        self.assertEqual(st, 200)

    def test_remove_fora_dos_peers_nao_chama_ninguem(self):
        st, _, body = self.post("/api/machines/remove", {"url": self.fake_url})
        self.assertEqual(st, 404, body)
        time.sleep(0.2)
        self.assertEqual(Recorder.calls, [])
        # controle: com a máquina pareada, o aviso vai (com o token) para o painel dela
        net.add_peer("http://127.0.0.1:1", "maq-x", "idx", self.fake_url)
        try:
            st, _, body = self.post("/api/machines/remove", {"url": "http://127.0.0.1:1"})
            self.assertEqual(st, 200, body)
            self.assertEqual(Recorder.calls[0][:2], ("/api/peers/remove", f"Bearer {TOKEN}"))
        finally:
            net.remove_peer("http://127.0.0.1:1")

    # ------------------------------------------------ acesso pela rede
    def test_outro_aparelho_sem_cookie(self):
        st, h, body = self.req("GET", "/", remote=True)
        self.assertEqual(st, 401)
        self.assertIn(b"panel-url", body)
        self.assertNotIn(b"api/state", body)
        for path in ("/api/state", "/api/machines", "/api/history", "/img/now-local.png", "/tela/frame.jpg"):
            self.assertEqual(self.req("GET", path, remote=True)[0], 401, path)
        self.assertEqual(self.req("GET", "/tela", remote=True)[0], 401)
        self.assertEqual(self.post("/api/pair/code", {}, remote=True)[0], 401)
        self.assertEqual(self.post("/api/settings", {"fps": 3}, remote=True)[0], 401)
        self.assertEqual(self.req("GET", "/img/icon.png", remote=True)[0], 200)
        # cookie errado também não
        st, _, _ = self.req("GET", "/api/state", remote=True,
                            headers={"Cookie": f"{self.auth.cookie_name(self.remote.server_port)}=abc"})
        self.assertEqual(st, 401)

    def test_dns_rebinding_nao_conta_como_local(self):
        st, _, _ = self.req("GET", "/api/state", headers={"Host": "evil.example:8788"})
        self.assertEqual(st, 401)

    def test_link_com_chave(self):
        key = self.auth.panel_key()
        mode = stat.S_IMODE(os.stat(self.auth.KEY_FILE).st_mode)
        self.assertEqual(mode, 0o600)
        self.assertNotEqual(key, TOKEN)
        st, h, body = self.req("GET", "/?key=" + key + "&lang=en", remote=True)
        self.assertEqual(st, 200)
        sc = h.get("Set-Cookie")
        self.assertIn("HttpOnly", sc)
        self.assertIn("SameSite=Strict", sc)
        self.assertNotIn(key, sc)
        self.assertNotIn(key.encode(), body)               # a página leva para a URL sem a chave
        self.assertIn(b'"/?lang=en"', body)
        st, _, _ = self.req("GET", "/?key=errada", remote=True)
        self.assertEqual(st, 401)
        # com o cookie: liberado, inclusive /tela e ações
        SET.save({**SET.load(), "ntfy_topic": "topico-secreto"})
        st, _, body = self.req("GET", "/api/state", remote=True, headers={"Cookie": self.cookie()})
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(body)["settings"]["ntfy_topic"], "topico-secreto")
        self.assertFalse(json.loads(body)["access"]["local"])
        self.assertEqual(self.req("GET", "/tela", remote=True, headers={"Cookie": self.cookie()})[0], 200)
        self.assertEqual(self.post("/api/settings", {"fps": 3}, remote=True, headers={"Cookie": self.cookie()})[0], 200)
        # o link só é entregue para o navegador desta máquina
        self.assertEqual(self.req("GET", "/api/panel-url", remote=True, headers={"Cookie": self.cookie()})[0], 403)
        st, _, body = self.req("GET", "/api/panel-url")
        self.assertEqual(st, 200)
        self.assertIn(key, json.loads(body)["url"])
        # ?key= direto num recurso (VLC/Home Assistant) também vale
        self.assertEqual(self.req("GET", "/tela/frame.jpg?key=" + key, remote=True)[0], 200)

    def test_token_do_grupo_vale_entre_peers(self):
        st, _, _ = self.req("GET", "/api/state", remote=True, headers={"Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(st, 200)

    def test_modo_off_esconde_segredos(self):
        self.write_cfg('panel_auth = "off"\n')
        try:
            SET.save({**SET.load(), "ntfy_topic": "topico-secreto"})
            st, _, body = self.req("GET", "/api/state", remote=True)
            self.assertEqual(st, 200)
            s = json.loads(body)["settings"]
            self.assertEqual(s["ntfy_topic"], "")
            self.assertTrue(s["ntfy_topic_set"])
            self.assertNotIn(b"topico-secreto", body)
            # CSRF continua valendo no modo aberto
            self.assertEqual(self.post("/api/settings", {"fps": 3}, remote=True, csrf=False)[0], 403)
        finally:
            self.write_cfg()

    # ------------------------------------------------ validação de entrada
    def test_cor_invalida(self):
        st, _, _ = self.post("/api/settings", {"colors": {"maq-seg": "#zzzzzz"}})
        self.assertEqual(st, 400)
        st, _, _ = self.post("/api/settings", {"colors": {"maq-seg": "red;x"}})
        self.assertEqual(st, 400)
        # mesmo que chegue por replicação ou arquivo, validate descarta e o desenho não quebra
        v = SET.validate({"colors": {"a": "#zzzzzz", "b": "#12345g", "c": "#00FF88"}})
        self.assertEqual(v["colors"], {"c": "#00ff88"})
        cur = SET.load()
        SET.save({**cur, "colors": {"maq-seg": "#gg0000"}, "rev": cur.get("rev", 0) + 1})
        img = self.P.PANEL.render("layout", "cards", "demo")
        self.assertIsNotNone(img)
        st, _, _ = self.post("/api/settings", {"colors": {"maq-seg": "#00aa11"}})
        self.assertEqual(st, 200)

    def test_entradas_invalidas(self):
        self.assertEqual(self.post("/api/force", {"mode": "sleep", "seconds": "abc"})[0], 400)
        self.assertEqual(self.post("/api/force", {"mode": "sleep", "seconds": [1]})[0], 400)
        self.assertEqual(self.post("/api/force", {"mode": "<script>", "seconds": 5})[0], 400)
        self.assertEqual(self.post("/api/force", {"mode": "sleep", "seconds": "7"})[0], 200)
        self.assertEqual(self.post("/api/settings", [1, 2])[0], 400)
        self.assertEqual(self.post("/api/settings", {"dreams": []})[0], 400)
        self.assertEqual(self.post("/api/settings", {"fps": "muito"})[0], 400)
        self.assertEqual(self.post("/api/settings", {"layout": "nao-existe"})[0], 400)
        self.assertEqual(self.post("/api/settings", {"ntfy_server": "javascript:alert(1)"})[0], 400)
        st, _, body = self.post("/api/settings", {"dreams": "false"})
        self.assertEqual(st, 200)
        self.assertIs(json.loads(body)["settings"]["dreams"], False)
        self.assertIs(SET.validate({"dreams": "off"})["dreams"], False)
        self.assertIs(SET.validate({"dreams": "1"})["dreams"], True)
        st, _, _ = self.req("POST", "/api/settings", raw=b"{nao-json", headers={"Content-Type": "application/json", "X-Byorzin": "1"})
        self.assertEqual(st, 400)

    def test_corpo_grande_e_content_length_invalido(self):
        st, _, _ = self.req("POST", "/api/settings", raw=b"x" * 100_000,
                            headers={"Content-Type": "application/json", "X-Byorzin": "1"})
        self.assertEqual(st, 413)
        c = http.client.HTTPConnection("127.0.0.1", self.local.server_port, timeout=5)
        c.putrequest("POST", "/api/settings")
        c.putheader("Content-Type", "application/json")
        c.putheader("X-Byorzin", "1")
        c.putheader("Content-Length", "-5")
        c.endheaders()
        self.assertEqual(c.getresponse().status, 400)
        c.close()

    # ------------------------------------------------ replicação
    def test_sync_por_rev(self):
        st, _, body = self.post("/api/settings", {"fps": 2})
        mine = json.loads(body)["settings"]
        st, _, body = self.post("/api/settings", {"fps": 3})
        self.assertEqual(json.loads(body)["settings"]["rev"], mine["rev"] + 1)
        cur = SET.load()
        auth_h = {"Authorization": f"Bearer {TOKEN}"}
        self.assertEqual(self.post("/api/sync", {**cur, "fps": 7, "rev": cur["rev"] + 5}, csrf=False)[0], 401)
        # relógio adiantado mas rev menor: não vence
        st, _, body = self.post("/api/sync", {**cur, "fps": 1, "rev": cur["rev"] - 1, "updated_at": time.time() + 9999},
                                headers=auth_h, csrf=False)
        self.assertEqual((st, json.loads(body)["applied"]), (200, False))
        self.assertEqual(SET.load()["fps"], 3)
        # rev maior vence mesmo com relógio atrasado
        st, _, body = self.post("/api/sync", {**cur, "fps": 6, "rev": cur["rev"] + 1, "updated_at": 1000},
                                headers=auth_h, csrf=False)
        self.assertTrue(json.loads(body)["applied"])
        self.assertEqual(SET.load()["fps"], 6)
        self.assertEqual(SET.load()["rev"], cur["rev"] + 1)

    def test_update_concorrente_nao_perde_rev(self):
        r0 = SET.load().get("rev", 0)
        ts = [threading.Thread(target=self.P.PANEL.update, args=({"fps": 1 + i % 8}, False)) for i in range(20)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(self.P.PANEL.current()["rev"], r0 + 20)

    # ------------------------------------------------ tela no navegador
    def test_limite_de_streams(self):
        from byorzin_monitor.display.backends import web
        held = 0
        while web._streams.acquire(blocking=False):
            held += 1
        try:
            st, _, _ = self.req("GET", "/tela/stream.mjpg")
            self.assertEqual(st, 503)
        finally:
            for _ in range(held):
                web._streams.release()

    def test_csp_na_pagina(self):
        st, h, body = self.req("GET", "/")
        self.assertEqual(st, 200)
        csp = h.get("Content-Security-Policy")
        self.assertIn("script-src 'nonce-", csp)
        import re
        self.assertIsNone(re.search(rb'\son[a-z]+="', body))       # nenhum handler inline no HTML

    # ------------------------------------------------ relógio do detalhe da sessão
    def test_detalhe_com_relogio_adiantado(self):
        now = time.time()
        d = {"served_at": now + 600, "session": {"since": now + 300, "last": now + 590,
                                                 "subagents": [{"since": now + 500}]},
             "events": [{"ts": now + 580}]}
        off = self.P.clock_offset(d, now, None)
        self.assertAlmostEqual(off, 600, delta=1)
        self.P.unskew_session(d, off)
        self.assertLess(d["session"]["last"], now)
        self.assertLess(d["events"][0]["ts"], now)
        self.assertAlmostEqual(d["session"]["since"], now - 300, delta=1)
        # sem served_at/ts: usa o cabeçalho Date
        from email.utils import formatdate
        self.assertAlmostEqual(self.P.clock_offset({}, now, formatdate(now + 120, usegmt=True)), 120, delta=2)


if __name__ == "__main__":
    unittest.main()
