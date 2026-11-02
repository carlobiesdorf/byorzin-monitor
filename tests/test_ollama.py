import _env
import json
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from byorzin_monitor.ollama import LlmWatcher

PS = {"models": []}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps(PS).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def model(exp):
    return {"name": "qwen3:14b", "size_vram": 9 * 2 ** 30, "expires_at": exp}


class TestOllama(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        self.t = 1000.0
        self.w = LlmWatcher(f"http://127.0.0.1:{self.srv.server_port}", clock=lambda: self.t)

    def step(self, dt=3, gpu=None):
        self.t += dt
        self.w.poll(gpu, 30)
        return self.w.sessions(60)

    def test_carregado_parado_nao_aparece(self):
        PS["models"] = [model("A")]
        self.assertEqual(self.step(), [])
        self.assertEqual(self.step(), [])

    def test_gerando_por_expires_e_por_gpu(self):
        PS["models"] = [model("A")]
        self.step()
        PS["models"] = [model("B")]           # keep-alive renovado = requisição nova
        ss = self.step()
        self.assertEqual(len(ss), 1)
        s = ss[0]
        self.assertEqual((s["kind"], s["status"], s["project"], s["id"]), ("llm", "working", "qwen3:14b", "llm:qwen3:14b"))
        self.assertEqual(s["vram_gb"], 9.0)
        self.assertEqual(self.step()[0]["status"], "working")       # segura alguns segundos
        self.assertEqual(self.step(15)[0]["status"], "idle")        # parou: fica ocioso um tempo
        self.assertEqual(self.step(70), [])                          # depois some
        self.assertEqual(self.step(gpu=80)[0]["status"], "working")  # GPU ocupada também conta

    def test_modelo_novo_carregando(self):
        PS["models"] = []
        self.step()
        PS["models"] = [model("A")]
        self.assertEqual(self.step()[0]["status"], "working")
        PS["models"] = []
        self.assertEqual(self.step(), [])

    def test_sem_ollama(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        w = LlmWatcher(f"http://127.0.0.1:{port}", clock=lambda: self.t)
        w.poll(90, 30)
        self.assertEqual(w.sessions(), [])
        self.assertFalse(w.ok)
        self.assertGreater(w.next_poll, self.t + 10)     # não insiste a cada ciclo


if __name__ == "__main__":
    unittest.main()
