import _env  # noqa: F401  (isola o ambiente antes dos imports)
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from byorzin_monitor.alerts import Alerts
from byorzin_monitor.display.effects import AlertFX


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def ev(name, ts, sid="s1", **kw):
    return {"session_id": sid, "hook_event_name": name, "ts": ts, "project": "proj", **kw}


class TestAlerts(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.cfg = {"alert_cooldown_seconds": 90, "done_minutes": 5, "alert_idle": True}
        self.sent = []
        self.a = Alerts("maq", lambda: self.cfg, clock=self.clock, sender=lambda *x: self.sent.append(x))

    def feed(self, name, dt=0, **kw):
        self.clock.t += dt
        self.a.on_event(ev(name, self.clock.t, **kw))

    def types(self):
        return [x["type"] for x in self.a.recent()]

    def test_waiting_uma_vez_por_transicao(self):
        self.feed("UserPromptSubmit")
        self.feed("PermissionRequest", 1)
        self.feed("Notification", 1, notification_type="permission_prompt")   # mesmo pedido, 2º aviso
        self.assertEqual(self.types(), ["waiting"])
        self.feed("PostToolUse", 5)
        self.feed("PermissionRequest", 5)          # nova transição, mas dentro do intervalo mínimo
        self.assertEqual(self.types(), ["waiting"])
        self.feed("PostToolUse", 5)
        self.feed("PermissionRequest", 100)        # depois do intervalo: avisa de novo
        self.assertEqual(self.types(), ["waiting", "waiting"])
        self.assertEqual(self.a.recent()[0]["reason"], "permissão")

    def test_ociosa_desligavel(self):
        self.cfg["alert_idle"] = False
        self.feed("Notification", notification_type="idle_prompt")
        self.assertEqual(self.types(), [])
        self.feed("Notification", 1, notification_type="elicitation_dialog")
        self.assertEqual(self.types(), [])        # já estava esperando: não é transição

    def test_releitura_nao_avisa(self):
        self.a.on_event(ev("PermissionRequest", self.clock.t - 3600))
        self.assertEqual(self.types(), [])

    def test_terminou_depois_de_n_minutos(self):
        self.feed("UserPromptSubmit")
        self.feed("PreToolUse", 60, tool_name="Bash")
        self.feed("Stop", 120)                      # 3 min: curto demais
        self.assertEqual(self.types(), [])
        self.feed("UserPromptSubmit", 10)
        self.feed("PreToolUse", 200, tool_name="Bash")
        self.feed("Stop", 200)                      # 6min40
        self.assertEqual(self.types(), ["done"])
        self.assertEqual(self.a.recent()[0]["worked_s"], 400)

    def test_ociosa_depois_de_terminou_nao_repete(self):
        self.feed("UserPromptSubmit")
        self.feed("PermissionRequest", 10)
        self.feed("PostToolUse", 300)
        self.feed("Stop", 10)                       # waiting e done têm intervalos separados
        self.feed("Notification", 60, notification_type="idle_prompt")
        self.assertEqual(self.types(), ["waiting", "done"])

    def test_ntfy_desligado_por_padrao(self):
        self.feed("PermissionRequest")
        time.sleep(0.05)
        self.assertEqual(self.sent, [])

    def test_ntfy_servidor_falso(self):
        got = []

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                got.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                self.send_response(200)
                self.end_headers()

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            a = Alerts("maq", lambda: {**self.cfg, "ntfy_enabled": True, "ntfy_topic": "tópico-x",
                                       "ntfy_server": f"http://127.0.0.1:{srv.server_port}"}, clock=self.clock)
            a.on_event(ev("PermissionRequest", self.clock.t))
            a.on_event(ev("Notification", self.clock.t, notification_type="permission_prompt"))
            for _ in range(50):
                if got:
                    break
                time.sleep(0.05)
            time.sleep(0.1)
            self.assertEqual(len(got), 1)
            path, body = got[0]
            self.assertEqual(path, "/")
            self.assertEqual(body["topic"], "tópico-x")
            self.assertEqual(body["title"], "Esperando você")
            self.assertIn("proj @ maq", body["message"])
        finally:
            srv.shutdown()


class FakeView:
    def __init__(self, alerts):
        self.alive = [{"host": "maq", "alerts": alerts}]


class TestAlertFX(unittest.TestCase):
    def test_efeito_por_alerta_novo(self):
        fx, now = AlertFX(), time.time()
        cfg = {"alert_screen_seconds": 8}
        v = FakeView([{"key": "k1", "ts": now - 2, "type": "waiting"}])
        fx.update(v, cfg, now)
        self.assertTrue(fx.framing(now + 7))
        self.assertTrue(fx.max_brightness(cfg, now + 1))
        fx.update(v, cfg, now + 20)                 # mesmo alerta de novo: não reacende
        self.assertFalse(fx.framing(now + 21))

    def test_alerta_velho_ignorado(self):
        fx, now = AlertFX(), time.time()
        fx.update(FakeView([{"key": "k", "ts": now - 600, "type": "waiting"}]), {}, now)
        self.assertFalse(fx.framing(now))

    def test_comemoracao(self):
        fx, now = AlertFX(), time.time()
        fx.update(FakeView([{"key": "d", "ts": now, "type": "done", "label": "x", "worked_s": 700}]), {}, now)
        self.assertEqual(fx.celebrating(now + 1)["label"], "x")
        self.assertIsNone(fx.celebrating(now + 30))
        fx2 = AlertFX()
        fx2.update(FakeView([{"key": "d", "ts": now, "type": "done"}]), {"done_celebrate": False}, now)
        self.assertIsNone(fx2.celebrating(now))


if __name__ == "__main__":
    unittest.main()
