# Renderização em alta resolução: a tela USB (escala 1) continua byte a byte igual, a escala alta
# desenha o mesmo quadro K vezes maior sem desalinhar, e as rotas /tela e /img aceitam ?scale=.
import _env  # noqa: F401
import io
import sys
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from PIL import Image, ImageChops, ImageStat

import hd_frames
from byorzin_monitor.display import scenes as S

# sha256 (20 primeiros) dos quadros em escala 1, gerados ANTES da alta resolução existir.
# Dependem de Pillow, cairosvg e das fontes DejaVu instaladas; se uma atualização dessas mudar
# o desenho de propósito, regenere com: cd tests && PYTHONPATH=.. python hd_frames.py
GOLDEN = {
    "layout-cards": "4115685fe4a933335245",
    "layout-lista": "fda9a1e4b5e6d1d7dcf0",
    "layout-foco": "14a0f011470256be47bd",
    "layout-equipe": "d3a49e57482627622743",
    "layout-grade": "51d70fceb2f35fabf19d",
    "layout-palco": "cd9627121e09042c0777",
    "layout-atividade": "bf7ac198e43e66829b3e",
    "layout-dashboard": "0aa631e93434d117c8bc",
    "layout-maquinas": "3c7cdeae0e11d592130c",
    "idle-awake": "54675b7b16c36463bb52",
    "idle-sleepy": "57b05131369356029dae",
    "idle-sleep": "d31d998c7fd6c215a713",
    "idle-dream": "bfe2653a8380279e7e5a",
    "wake": "961fc755a0e64f1d17ca",
    "limit": "15ccbf887190bb285463",
    "host": "07b53de9f8d4d6eb6e87",
    "done": "c3b9b1c57fa2fdb4dbbe",
    "alert": "572d17ed8f5a7faec97c",
    "llm-face": "15d87be74f42b227cb32",
}


def _diff(a, b):
    return sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3


class EscalaUm(unittest.TestCase):
    # a referência é do Linux (cairo e fontes do Debian/Ubuntu); no macOS o cairo do Homebrew
    # pode diferir em pixels de borda, então lá este teste não vale
    @unittest.skipUnless(sys.platform == "linux", "referência gerada no Linux")
    def test_tela_usb_byte_a_byte_igual(self):
        self.assertEqual(hd_frames.digests(), GOLDEN)

    def test_escala_padrao_e_1(self):
        self.assertEqual(S.scale(), 1)
        im, d = S.canvas()
        self.assertEqual(im.size, (480, 320))
        self.assertNotIsInstance(d, S.HDDraw)      # K=1: ImageDraw puro, sem proxy

    def test_clamp(self):
        self.assertEqual([S.clamp_scale(x) for x in (0, 1, "3", 9, "x", None, 2.7)], [1, 1, 3, 4, 1, 1, 2])


class EscalaAlta(unittest.TestCase):
    def test_tamanho_e_alinhamento(self):
        """Em K=2..4 o quadro tem 480K x 320K e, reduzido de volta, bate com o de K=1
        (só o antisserrilhado do texto difere): nada sai do lugar."""
        with hd_frames.frozen():
            fr = hd_frames.frames()
            for name, f in fr.items():
                base = f()
                for k in (2, 4):
                    with S.scaled(k):
                        im = f()
                    self.assertEqual(im.size, (480 * k, 320 * k), name)
                    small = im.resize((480, 320), Image.BOX)
                    self.assertLess(_diff(base, small), 8, f"{name} K={k} desalinhado")

    def test_volta_para_1_depois_do_bloco(self):
        with S.scaled(3):
            self.assertEqual(S.scale(), 3)
            self.assertEqual(S.F(10).size, 30)
        self.assertEqual(S.scale(), 1)
        self.assertEqual(S.F(10).size, 10)

    def test_textlength_logico(self):
        with S.scaled(4):
            _, d = S.canvas()
            n4 = d.textlength("Byorzin trabalhando", font=S.F(12))
        _, d = S.canvas()
        n1 = d.textlength("Byorzin trabalhando", font=S.F(12))
        self.assertAlmostEqual(n4, n1, delta=n1 * 0.05)

    def test_escala_por_thread(self):
        """O painel desenha escalas diferentes em threads diferentes: uma não vaza na outra."""
        out, go = {}, threading.Barrier(2)

        def run(k):
            with S.scaled(k):
                go.wait()
                out[k] = S.canvas()[0].size

        ts = [threading.Thread(target=run, args=(k,)) for k in (1, 4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(out, {1: (480, 320), 4: (1920, 1280)})

    def test_moldura_acompanha_a_escala(self):
        from byorzin_monitor.display.effects import alert_frame
        with S.scaled(3):
            im, _ = S.canvas()
            framed = alert_frame(im, 0.2)
        # espessura >= 4 px lógicos = 12 px físicos
        self.assertNotEqual(framed.getpixel((11, 600)), im.getpixel((11, 600)))

    def test_cache_de_sprites_limitado(self):
        lru = S._ByteLRU(100 * 100 * 4 * 3)
        for i in range(10):
            lru.get(i, lambda: Image.new("RGBA", (100, 100)))
        self.assertLessEqual(lru.used, lru.budget)
        self.assertEqual(list(lru.d), [7, 8, 9])


class Rotas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from byorzin_monitor.panel import server
        from test_web import FakePanel

        class P(FakePanel):
            def current(self):
                return self.settings.get()
            render = server.Panel.render

        server.PANEL = P()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def size(self, path):
        with urllib.request.urlopen(self.base + path, timeout=20) as r:
            return Image.open(io.BytesIO(r.read())).size

    def test_scale_from(self):
        from byorzin_monitor.display.backends.web import scale_from
        cases = [({}, 1), ({"scale": ["2"]}, 2), ({"scale": ["99"]}, 4), ({"w": ["1920"]}, 4),
                 ({"w": ["1000"]}, 3), ({"w": ["nan"]}, 1), ({"w": ["-5"]}, 1), ({"scale": ["2"], "w": ["1920"]}, 2)]
        for q, k in cases:
            self.assertEqual(scale_from(q), k, q)

    def test_frame_por_escala(self):
        from byorzin_monitor.panel import server
        self.assertEqual(self.size("/tela/frame.jpg?layout=grade"), (480, 320))
        self.assertEqual(self.size("/tela/frame.jpg?layout=grade&scale=2"), (960, 640))
        self.assertEqual(self.size("/tela/frame.jpg?layout=grade&w=1920"), (1920, 1280))
        hub = server.PANEL._tela_hub
        self.assertIn("grade", hub.cache)              # escala 1: mesma chave de antes
        self.assertIn(("grade", 2), hub.cache)
        self.assertIn(("grade", 4), hub.cache)

    def test_stream_com_escala(self):
        with urllib.request.urlopen(self.base + "/tela/stream.mjpg?scale=2", timeout=20) as r:
            head = r.read(120)
            body = head + r.read(int(head.split(b"Content-Length: ")[1].split(b"\r\n")[0]) + 200)
        jpg = body[body.index(b"\xff\xd8"):]
        self.assertEqual(Image.open(io.BytesIO(jpg)).size, (960, 640))

    def test_pagina_calcula_escala(self):
        with urllib.request.urlopen(self.base + "/tela", timeout=20) as r:
            page = r.read()
        self.assertIn(b"devicePixelRatio", page)
        self.assertIn(b"scale=", page)
        self.assertNotIn(b"PAGE_MAX_SCALE", page)

    def test_previas_do_painel(self):
        self.assertEqual(self.size("/img/layout/cards.png"), (480, 320))
        self.assertEqual(self.size("/img/layout/cards.png?scale=2"), (960, 640))
        self.assertEqual(self.size("/img/scene/done.png?scale=3"), (1440, 960))
        self.assertEqual(self.size("/img/scene/alert.png?scale=bobagem"), (480, 320))


if __name__ == "__main__":
    unittest.main()
