import _env  # noqa: F401
import os
import unittest

from PIL import Image

from byorzin_monitor.display.backends import open_backend


class SimTest(unittest.TestCase):
    def test_folder_of_frames(self):
        d = os.path.join(_env.TMP, "sim")
        scr = open_backend("sim", d, size="320x480")
        self.assertEqual(scr.size, (320, 480))
        img = Image.new("RGB", (320, 480))
        scr.show(img)
        scr.show(img)                                        # repetido: não grava de novo
        img.putpixel((0, 0), (255, 255, 255))
        scr.show(img)
        self.assertEqual(sorted(os.listdir(d)), ["quadro-00001.png", "quadro-00002.png"])

    def test_single_png(self):
        p = os.path.join(_env.TMP, "sim.png")
        scr = open_backend("sim", p)
        scr.show(Image.new("RGB", (480, 320), (9, 9, 9)))
        self.assertEqual(Image.open(p).getpixel((0, 0)), (9, 9, 9))


if __name__ == "__main__":
    unittest.main()
