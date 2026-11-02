import _env  # noqa: F401
import unittest

import numpy as np
from PIL import Image

from byorzin_monitor.display.engine import fit_to


def logical():
    img = Image.new("RGB", (480, 320), (255, 0, 0))
    img.paste((0, 0, 255), (0, 0, 10, 10))          # marca no canto superior esquerdo
    return img


class FitTo(unittest.TestCase):
    def test_same_size_is_untouched(self):
        img = logical()
        self.assertIs(fit_to(img, (480, 320)), img)

    def test_landscape_to_portrait_rotates(self):
        out = fit_to(logical(), (320, 480))
        self.assertEqual(out.size, (320, 480))
        a = np.asarray(out)
        # girado 90° no sentido anti-horário: a marca vai para o canto inferior esquerdo
        self.assertEqual(tuple(a[475, 4]), (0, 0, 255))
        self.assertEqual(tuple(a[4, 4]), (255, 0, 0))

    def test_scale_down_exact(self):
        out = fit_to(logical(), (240, 160))
        self.assertEqual(out.size, (240, 160))
        self.assertGreater(np.asarray(out)[80, 120, 0], 200)

    def test_scale_up_with_black_borders(self):
        out = fit_to(logical(), (800, 480))                # 480x320 -> 720x480 + bordas de 40 px
        a = np.asarray(out)
        self.assertEqual(out.size, (800, 480))
        self.assertEqual(tuple(a[240, 10]), (0, 0, 0))
        self.assertEqual(tuple(a[240, 790]), (0, 0, 0))
        self.assertGreater(a[240, 400, 0], 200)

    def test_terminal_like_size(self):
        out = fit_to(logical(), (100, 48))
        self.assertEqual(out.size, (100, 48))


if __name__ == "__main__":
    unittest.main()
