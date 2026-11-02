import _env  # noqa: F401
import unittest

import numpy as np
from PIL import Image

from _env import FakeSerial
from byorzin_monitor.display.backends.turing_a import TILE, TuringA, _rects, rgb565


def covered(rects, tiles):
    m = np.zeros_like(tiles)
    for x0, y0, x1, y1 in rects:
        assert 0 <= x0 < x1 <= tiles.shape[1] and 0 <= y0 < y1 <= tiles.shape[0]
        m[y0:y1, x0:x1] = True
    return m


class Rects(unittest.TestCase):
    def test_single_tile(self):
        t = np.zeros((20, 30), bool)
        t[3, 4] = True
        self.assertEqual(_rects(t), [[4, 3, 5, 4]])

    def test_block_merges_rows(self):
        t = np.zeros((20, 30), bool)
        t[2:6, 5:9] = True
        self.assertEqual(_rects(t), [[5, 2, 9, 6]])

    def test_far_apart_split(self):
        t = np.zeros((20, 30), bool)
        t[0, 0] = t[0, 20] = True
        self.assertEqual(len(_rects(t)), 2)

    def test_random_always_covers(self):
        rng = np.random.default_rng(1)
        for _ in range(50):
            t = rng.random((20, 30)) < 0.1
            self.assertTrue((covered(_rects(t), t) >= t).all())


class Encoding(unittest.TestCase):
    def test_rgb565(self):
        a = np.array([[[255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 255, 255]]], np.uint8)
        self.assertEqual(list(rgb565(a)[0]), [0xF800, 0x07E0, 0x001F, 0xFFFF])

    def test_full_frame_then_partial(self):
        ser = FakeSerial()
        scr = TuringA(ser=ser)
        ser.out.clear()
        img = Image.new("RGB", (480, 320), (255, 0, 0))
        self.assertEqual(scr.show(img), 480 * 320)
        head, body = bytes(ser.out[:6]), bytes(ser.out[6:])
        # cabeçalho: x=0 y=0 ex=479 ey=319, comando 197
        self.assertEqual(head, bytes([0, 0, (479 >> 6), ((479 & 63) << 2) + (319 >> 8), 319 & 255, 197]))
        self.assertEqual(len(body), 480 * 320 * 2)
        self.assertEqual(body[:2], b"\x00\xf8")             # 0xF800 little-endian
        ser.out.clear()
        self.assertEqual(scr.show(img), 0)                   # nada mudou: nada enviado
        self.assertEqual(len(ser.out), 0)
        img.paste((0, 0, 255), (20, 20, 21, 21))
        self.assertEqual(scr.show(img), TILE * TILE)         # só o tile 16x16 que mudou
        self.assertEqual(len(ser.out), 6 + TILE * TILE * 2)


if __name__ == "__main__":
    unittest.main()
