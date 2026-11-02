# Coletor real (porta de teste) + painel numa porta livre, com uma sessão falsa.
import _env
import json
import os
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from byorzin_monitor import common
from byorzin_monitor.collector import Collector, make_handler

SID = "11111111-2222-3333-4444-555555555555"


def get(url, token=None):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"} if token else {})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r)


class TestRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = common.load_config()
        assert cfg["port"] == 58797, "ambiente de teste não isolado"
        common.ensure_state_dir()
        from byorzin_monitor.sysinfo import proc_start
        start = proc_start(os.getpid())      # None no macOS (lá vale só o PID)
        (common.CLAUDE_DIR / "sessions" / "t.json").write_text(json.dumps(
            {"sessionId": SID, "pid": os.getpid(), "procStart": start, "cwd": "/x/meu-projeto",
             "startedAt": (time.time() - 900) * 1000}))
        now = time.time()
        evs = [{"session_id": SID, "hook_event_name": "UserPromptSubmit", "ts": now - 700, "project": "meu-projeto"},
               {"session_id": SID, "hook_event_name": "PreToolUse", "tool_name": "Bash", "ts": now - 650, "project": "meu-projeto"},
               {"session_id": SID, "hook_event_name": "Stop", "ts": now - 2, "project": "meu-projeto"}]
        with open(common.EVENTS_FILE, "a") as f:
            for e in evs:
                f.write(json.dumps(e) + "\n")
        cls.col = Collector(cfg)
        cls.col.build()
        cls.csrv = ThreadingHTTPServer(("127.0.0.1", cfg["port"]), make_handler(cls.col, cfg["token"]))
        threading.Thread(target=cls.csrv.serve_forever, daemon=True).start()
        from byorzin_monitor.panel import server as P
        P.PANEL = P.Panel()
        cls.psrv = ThreadingHTTPServer(("127.0.0.1", 0), P.H)
        threading.Thread(target=cls.psrv.serve_forever, daemon=True).start()
        cls.purl = f"http://127.0.0.1:{cls.psrv.server_port}"
        for _ in range(40):        # espera o Fetcher do painel buscar o coletor
            if any(st for _, st in P.PANEL.fetcher.sources):
                break
            time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        for srv in (cls.csrv, cls.psrv):
            srv.shutdown()
            srv.server_close()

    def test_coletor_exige_token(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            get("http://127.0.0.1:58797/history")
        self.assertEqual(e.exception.code, 401)
        h = get("http://127.0.0.1:58797/history?days=7", "teste")
        self.assertEqual(h["host"], "maq-teste")
        today = time.strftime("%Y-%m-%d")
        self.assertEqual(h["days"][today]["tools"], {"Bash": 1})

    def test_alerta_terminou_no_state(self):
        st = get(self.purl + "/api/state")
        al = [a for a in st["alerts"] if a["type"] == "done"]
        self.assertEqual(len(al), 1)
        self.assertEqual(al[0]["host"], "maq-teste")
        self.assertGreaterEqual(al[0]["worked_s"], 690)
        item = st["summary"]["list"][0]
        self.assertEqual(item["id"], SID)

    def test_detalhe_da_sessao(self):
        d = get(self.purl + f"/api/session?host=maq-teste&id={SID}")
        self.assertEqual(d["session"]["project"], "meu-projeto")
        self.assertEqual([e["hook_event_name"] for e in d["events"]], ["Stop", "PreToolUse", "UserPromptSubmit"])
        with self.assertRaises(urllib.error.HTTPError):
            get(self.purl + "/api/session?host=maq-teste&id=nao-existe")

    def test_historico_somado(self):
        h = get(self.purl + "/api/history?days=7")
        self.assertEqual(h["hosts"], ["maq-teste"])
        self.assertEqual(len(h["dates"]), 7)
        self.assertEqual(h["tools"], [["Bash", 1]])
        self.assertEqual(h["sessions"][-1], 1)

    def test_ajustes_novos(self):
        req = urllib.request.Request(self.purl + "/api/settings", method="POST",
                                     data=json.dumps({"ntfy_topic": "  meu-topico  ", "done_minutes": 999}).encode(),
                                     headers={"Content-Type": "application/json", "X-Byorzin": "1"})
        with urllib.request.urlopen(req, timeout=5) as r:
            s = json.load(r)["settings"]
        self.assertEqual(s["ntfy_topic"], "meu-topico")
        self.assertEqual(s["done_minutes"], 240)
        self.assertFalse(s["ntfy_enabled"])
        st = get(self.purl + "/api/state")
        keys = {k for _, fs in st["form"] for k, *_ in fs}
        self.assertTrue({"ntfy_server", "llm_session", "alert_screen"} <= keys)

    def test_previas_das_cenas_novas(self):
        for name in ("alert", "done"):
            with urllib.request.urlopen(self.purl + f"/img/scene/{name}.png", timeout=10) as r:
                self.assertEqual(r.headers["Content-Type"], "image/png")


if __name__ == "__main__":
    unittest.main()
