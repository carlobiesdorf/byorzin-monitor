import time
import unittest

from tests import _isolate  # noqa: F401
from byorzin_monitor import network as net
from byorzin_monitor.common import write_json_atomic
from byorzin_monitor.display.engine import Fetcher, View


def state(host, sessions, ts=None):
    return {"host": host, "ts": ts or time.time(), "sessions": sessions, "rate": None, "tokens": {},
            "events_recent": [], "last_activity": 0, "host_metrics": {}}


def sess(sid, status="working"):
    now = time.time()
    return {"id": sid, "project": sid, "title": None, "status": status, "since": now - 60, "last": now,
            "subagents": [{"id": "x", "type": "Explore", "tool": "Grep"}], "tokens": 0}


class TestView(unittest.TestCase):
    def test_maquina_offline(self):
        seen = time.time() - 7200
        off = {**state("notebook", [sess("antiga")]), "_offline": True, "_seen": seen}
        v = View([("desk", state("desk", [sess("a"), sess("b", "waiting")])), ("notebook", off), ("nunca", None)], {})
        self.assertEqual(v.hosts, [("desk", True), ("notebook", False), ("nunca", False)])
        self.assertEqual({s["id"] for s in v.sessions}, {"a", "b"})      # offline não conta como ativa
        self.assertEqual(v.host_seen, {"notebook": seen})
        m = {x["name"]: x for x in v.machines}
        self.assertTrue(m["desk"]["online"])
        self.assertEqual(len(m["desk"]["sessions"]), 2)
        self.assertFalse(m["notebook"]["online"])
        self.assertEqual(m["notebook"]["seen"], seen)
        self.assertEqual(m["notebook"]["sessions"][0]["status"], "offline")
        self.assertEqual(m["notebook"]["sessions"][0]["subagents"], [])
        self.assertFalse(m["nunca"]["online"])
        self.assertIsNone(m["nunca"]["seen"])


class TestFetcherOffline(unittest.TestCase):
    def test_ultimo_estado_do_disco(self):
        """Peer que não responde, com estado salvo de 1 h atrás: aparece offline, com 'visto há'."""
        dead = f"http://127.0.0.1:{_isolate.free_port()}"
        seen = time.time() - 3600
        write_json_atomic(net.SEEN_FILE, {dead: {"seen": seen, "name": "laptop",
                                                 "state": state("laptop", [sess("x")], seen)}})
        f = Fetcher({"port": _isolate.free_port(), "peers": [dead], "token": ""})
        f.start()
        deadline = time.time() + 5
        while time.time() < deadline and len(f.sources) < 2:
            time.sleep(0.1)
        src = dict(f.sources)
        self.assertIn("laptop", src)
        self.assertTrue(src["laptop"]["_offline"])
        self.assertAlmostEqual(src["laptop"]["_seen"], seen, delta=1)
        v = f.view({})
        self.assertEqual(v.sessions, [])
        self.assertIn(("laptop", False), v.hosts)


if __name__ == "__main__":
    unittest.main()
