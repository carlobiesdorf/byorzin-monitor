import json
import threading
import time
import unittest
from http.server import ThreadingHTTPServer

from tests import _isolate  # noqa: F401  (isola antes de importar o pacote)
from byorzin_monitor import network as net
from byorzin_monitor import pairing
from byorzin_monitor.common import CONFIG_FILE, load_config


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class TestCodes(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.p = pairing.Pairing(clock=self.clock)

    def err(self, ip, code):
        with self.assertRaises(pairing.PairError) as cm:
            self.p.check(ip, code)
        return cm.exception

    def test_ok_e_uso_unico(self):
        code = self.p.generate()["code"]
        self.assertEqual(len(code), 6)
        self.assertTrue(self.p.check("10.0.0.2", code))
        self.assertEqual(self.err("10.0.0.2", code).status, 410)     # já usado

    def test_codigo_com_espaco(self):
        code = self.p.generate()["code"]
        self.assertTrue(self.p.check("10.0.0.2", code[:3] + " " + code[3:]))

    def test_formato(self):
        self.p.generate()
        self.assertEqual(self.err("10.0.0.2", "12").status, 400)

    def test_sem_codigo(self):
        self.assertEqual(self.err("10.0.0.2", "123456").status, 410)

    def test_expira(self):
        code = self.p.generate()["code"]
        self.clock.t += pairing.CODE_TTL + 1
        e = self.err("10.0.0.2", code)
        self.assertEqual(e.status, 410)
        self.assertIn("expirado", e.msg)

    def test_errado_e_esgota(self):
        code = self.p.generate()["code"]
        wrong = "%06d" % ((int(code) + 1) % 10 ** 6)
        e = self.err("10.0.0.2", wrong)
        self.assertEqual(e.status, 403)
        self.assertIn("4 tentativas", e.msg)
        for _ in range(pairing.TRIES_PER_CODE - 1):
            self.err("10.0.0.2", wrong)
        # código invalidado: nem o certo vale mais
        self.assertEqual(self.err("10.0.0.2", code).status, 410)

    def test_forca_bruta_por_ip(self):
        for _ in range(pairing.IP_MAX_FAILS):
            code = self.p.generate()["code"]
            self.err("10.0.0.9", "%06d" % ((int(code) + 1) % 10 ** 6))
        code = self.p.generate()["code"]
        self.assertEqual(self.err("10.0.0.9", code).status, 429)     # bloqueado mesmo com o certo
        self.assertTrue(self.p.check("10.0.0.3", code))              # outro IP segue funcionando
        self.clock.t += pairing.IP_WINDOW + 1
        code = self.p.generate()["code"]
        self.assertTrue(self.p.check("10.0.0.9", code))              # janela passou

    def test_forca_bruta_distribuida(self):
        for i in range(pairing.GLOBAL_MAX_FAILS):
            code = self.p.generate()["code"]
            self.err(f"10.1.0.{i}", "%06d" % ((int(code) + 1) % 10 ** 6))
        code = self.p.generate()["code"]
        self.assertEqual(self.err("10.2.0.1", code).status, 429)


class TestConfig(unittest.TestCase):
    def test_set_config_preserva(self):
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text('# meu comentário\ntoken = "velho"\nport = 1234\n\n[extra]\npeers = "não mexer"\n')
        net.set_config(token="novo", peers=["http://1.2.3.4:8787"])
        txt = CONFIG_FILE.read_text()
        self.assertIn("# meu comentário", txt)
        self.assertIn('peers = "não mexer"', txt)
        cfg = load_config()
        self.assertEqual(cfg["token"], "novo")
        self.assertEqual(cfg["peers"], ["http://1.2.3.4:8787"])
        self.assertEqual(cfg["port"], 1234)

    def test_live_config(self):
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text('token = "a"\n')
        live = net.LiveConfig(every=0)
        self.assertEqual(live.token(), "a")
        time.sleep(0.01)
        net.set_config(token="b")
        self.assertEqual(live.token(), "b")

    def test_norm_url(self):
        self.assertEqual(net.norm_url("192.168.1.5", 8788), "http://192.168.1.5:8788")
        self.assertEqual(net.norm_url("http://x:9/", 8788), "http://x:9")


class TestHTTP(unittest.TestCase):
    """Painel de verdade (em thread) recebendo o pedido de pareamento de outra máquina."""

    @classmethod
    def setUpClass(cls):
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        cls.port = _isolate.free_port()
        CONFIG_FILE.write_text(f'token = "segredo-a"\npeers = []\nhostname = "maq-a"\nport = {_isolate.free_port()}\n'
                               f'panel_port = {cls.port}\ndiscovery = false\n')
        from byorzin_monitor.panel import server
        server.PANEL = server.Panel()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", cls.port), server.H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_fluxo(self):
        with self.assertRaises(pairing.PairError) as cm:
            pairing.post(self.base + "/api/pair/claim", {"code": "000000"})
        self.assertEqual(cm.exception.status, 410)
        code = pairing.post(self.base + "/api/pair/code", {})["code"]
        r = pairing.post(self.base + "/api/pair/claim", {"code": code, "id": "maqb", "host": "maq-b",
                                                         "port": 48787, "panel_port": 48788})
        self.assertEqual(r["token"], "segredo-a")
        self.assertEqual(r["host"], "maq-a")
        self.assertIn("http://127.0.0.1:48787", load_config()["peers"])
        self.assertEqual(net.machines_meta()["http://127.0.0.1:48787"]["panel"], "http://127.0.0.1:48788")
        # o estado do painel nunca expõe o token
        with __import__("urllib.request").request.urlopen(self.base + "/api/state") as resp:
            self.assertNotIn("segredo-a", resp.read().decode())
        # rotas entre peers exigem o token
        with self.assertRaises(pairing.PairError) as cm:
            pairing.post(self.base + "/api/peers/add", {"url": "http://9.9.9.9:8787"})
        self.assertEqual(cm.exception.status, 401)
        pairing.post(self.base + "/api/peers/add", {"url": "http://9.9.9.9:8787", "host": "x"}, token="segredo-a")
        self.assertIn("http://9.9.9.9:8787", load_config()["peers"])
        # despareamento vindo do outro lado (pelo id)
        pairing.post(self.base + "/api/peers/remove", {"id": "maqb", "port": 1}, token="segredo-a")
        self.assertNotIn("http://127.0.0.1:48787", load_config()["peers"])


if __name__ == "__main__":
    unittest.main()


def _guard_config(cls):
    """Os testes daqui reescrevem o config.toml do ambiente de teste comum: devolve o original
    ao fim de cada teste, para não afetar os outros módulos."""
    orig_setup, orig_teardown = cls.setUp, cls.tearDown

    def setUp(self):
        self._cfg_backup = CONFIG_FILE.read_text() if CONFIG_FILE.exists() else None
        orig_setup(self)

    def tearDown(self):
        try:
            orig_teardown(self)
        finally:
            if self._cfg_backup is None:
                CONFIG_FILE.unlink(missing_ok=True)
            else:
                CONFIG_FILE.write_text(self._cfg_backup)
    cls.setUp, cls.tearDown = setUp, tearDown
    orig_scls, orig_tcls = cls.setUpClass.__func__, cls.tearDownClass.__func__

    def setUpClass(k):
        k._cfg_backup_cls = CONFIG_FILE.read_text() if CONFIG_FILE.exists() else None
        orig_scls(k)

    def tearDownClass(k):
        try:
            orig_tcls(k)
        finally:
            if k._cfg_backup_cls is None:
                CONFIG_FILE.unlink(missing_ok=True)
            else:
                CONFIG_FILE.write_text(k._cfg_backup_cls)
    cls.setUpClass, cls.tearDownClass = classmethod(setUpClass), classmethod(tearDownClass)
    return cls


for _name, _obj in list(globals().items()):
    if isinstance(_obj, type) and issubclass(_obj, unittest.TestCase):
        _guard_config(_obj)
