import json
import time
import unittest

from tests import _isolate  # noqa: F401
from byorzin_monitor import network as net


class FakeLive:
    def __init__(self, **kw):
        self.cfg = kw

    def get(self):
        return self.cfg


class TestDiscovery(unittest.TestCase):
    def test_duas_instancias(self):
        dport = _isolate.free_port("udp")
        common = {"discovery_port": dport, "discovery_address": "127.255.255.255", "token": "NAO-VAZAR"}
        a = net.Announcer(FakeLive(hostname="maq-a", port=38787, panel_port=38788, **common))
        b = net.Announcer(FakeLive(hostname="maq-b", port=48787, panel_port=48788, **common))
        a.mid, b.mid = "id-a", "id-b"
        self.assertNotIn(b"NAO-VAZAR", a.message())
        self.assertNotIn("token", json.loads(a.message()))
        ls = net.Listener(dport, "127.255.255.255", own_id="id-a")      # a máquina A ouvindo
        for x in (ls, a, b):
            x.start()
        try:
            deadline = time.time() + 5
            while time.time() < deadline and not ls.items():
                time.sleep(0.1)
            found = {m["id"]: m for m in ls.items()}
        finally:
            for x in (ls, a, b):
                x.stop()
        self.assertEqual(set(found), {"id-b"})          # a própria máquina não aparece
        self.assertEqual(found["id-b"]["host"], "maq-b")
        self.assertEqual(found["id-b"]["port"], 48787)
        self.assertEqual(found["id-b"]["panel_port"], 48788)
        self.assertEqual(found["id-b"]["ip"], "127.0.0.1")

    def test_pergunta_responde_na_hora(self):
        """Quem chega depois não espera o próximo anúncio: pergunta e recebe resposta."""
        dport = _isolate.free_port("udp")
        a = net.Announcer(FakeLive(hostname="maq-a", port=1, panel_port=2, discovery_port=dport,
                                   discovery_address="127.255.255.255"))
        a.mid = "id-a"
        a.start()
        time.sleep(0.5)                                  # primeiro anúncio já passou
        ls = net.Listener(dport, "127.255.255.255", own_id="outro")
        ls.start()
        try:
            deadline = time.time() + 3
            while time.time() < deadline and not ls.items():
                time.sleep(0.05)
            self.assertEqual([m["id"] for m in ls.items()], ["id-a"])
        finally:
            a.stop()
            ls.stop()

    def test_ignora_lixo(self):
        ls = net.Listener(0, own_id="x")
        ls._take(b"nada", ("1.2.3.4", 1))
        ls._take(json.dumps({"app": "outro", "id": "z"}).encode(), ("1.2.3.4", 1))
        ls._take(json.dumps({"app": net.APP_TAG, "id": "z", "port": "abc"}).encode(), ("1.2.3.4", 1))
        self.assertEqual(ls.items(), [])

    def test_is_paired(self):
        cfg = {"peers": ["http://10.0.0.5:8787"]}
        self.assertTrue(net.is_paired({"id": "q", "ip": "10.0.0.5", "port": 8787}, cfg, {}))
        self.assertFalse(net.is_paired({"id": "q", "ip": "10.0.0.6", "port": 8787}, cfg, {}))
        self.assertTrue(net.is_paired({"id": "q", "ip": "10.0.0.6", "port": 8787}, cfg,
                                      {"http://10.0.0.5:8787": {"id": "q"}}))


if __name__ == "__main__":
    unittest.main()
