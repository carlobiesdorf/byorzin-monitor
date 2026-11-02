import time
import unittest

from tests import _isolate  # noqa: F401
from byorzin_monitor.display.demo import demo_view
from byorzin_monitor.display.engine import View
from byorzin_monitor.display.layouts import LAYOUTS
from byorzin_monitor.settings import LAYOUT_NAMES


class TestLayoutMaquinas(unittest.TestCase):
    def test_registrado(self):
        self.assertIn("maquinas", LAYOUTS)
        self.assertIn("maquinas", LAYOUT_NAMES)

    def test_demo(self):
        v = demo_view({})
        self.assertTrue(any(not m["online"] for m in v.machines))
        im = LAYOUTS["maquinas"](v, 1.3)
        self.assertEqual(im.size, (480, 320))
        self.assertGreater(len(im.getcolors(1 << 16) or []), 50)         # desenhou algo de verdade

    def test_vazio_e_muitas(self):
        self.assertEqual(LAYOUTS["maquinas"](View([], {}), 0).size, (480, 320))
        now = time.time()
        srcs = []
        for i in range(7):
            ss = [{"id": f"s{i}{j}", "project": f"p{j}", "status": "working", "since": now, "last": now,
                   "subagents": [], "tokens": 0} for j in range(i)]
            st = {"host": f"m{i}", "ts": now, "sessions": ss}
            if i % 3 == 0:
                st.update(_offline=True, _seen=now - 100 * i)
            srcs.append((f"m{i}", st))
        im = LAYOUTS["maquinas"](View(srcs, {}), 2.0)
        self.assertEqual(im.size, (480, 320))


if __name__ == "__main__":
    unittest.main()
