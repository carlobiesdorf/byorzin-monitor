import _env  # noqa: F401
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from byorzin_monitor.display.engine import View
from byorzin_monitor.panel import server
from byorzin_monitor.settings import Settings


class FakeFetcher:
    """Sem coletor: nenhuma máquina, o Byorzin fica ocioso."""

    def __init__(self):
        self.lock = threading.Lock()
        self.sources = []
        self.names = {}

    def view(self, settings=None):
        return View([], settings)


class FakePanel:
    def __init__(self):
        self.cfg = {"hostname": "teste", "port": 1, "panel_port": 1, "token": "x", "peers": []}
        self.settings = Settings()
        self.fetcher = FakeFetcher()
        self.lock = threading.Lock()


class TelaRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.PANEL = FakePanel()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=20) as r:
            return r.status, r.headers.get("Content-Type"), r.read()

    def test_page(self):
        st, ct, body = self.get("/tela")
        self.assertEqual(st, 200)
        self.assertIn("text/html", ct)
        self.assertIn(b"frame.jpg", body)
        self.assertIn(b"wakeLock", body)

    def test_frame_and_cache(self):
        st, ct, a = self.get("/tela/frame.jpg?layout=lista")
        self.assertEqual((st, ct), (200, "image/jpeg"))
        self.assertTrue(a.startswith(b"\xff\xd8"))
        hub = server.PANEL._tela_hub
        t1 = hub.cache["lista"][0]
        self.get("/tela/frame.jpg?layout=lista")                 # logo em seguida: vem do cache
        self.assertEqual(hub.cache["lista"][0], t1)
        self.get("/tela/frame.jpg?layout=naoexiste")              # layout inválido = o do painel
        self.assertIn(None, hub.cache)

    def test_mjpeg_stream(self):
        with urllib.request.urlopen(self.base + "/tela/stream.mjpg", timeout=20) as r:
            self.assertIn("multipart/x-mixed-replace", r.headers.get("Content-Type"))
            chunk = r.read(200)
        self.assertIn(b"--byorzinframe", chunk)
        self.assertIn(b"image/jpeg", chunk)

    def test_api_telas(self):
        import json
        st, _, body = self.get("/api/telas")
        kinds = {t["kind"] for t in json.loads(body)}
        self.assertTrue({"web", "terminal"} <= kinds)


if __name__ == "__main__":
    unittest.main()
