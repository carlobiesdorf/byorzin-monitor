import _env  # noqa: F401
import io
import unittest

from PIL import Image

from byorzin_monitor.display.backends.terminal import Terminal


class TerminalTest(unittest.TestCase):
    def setUp(self):
        self.out = io.StringIO()
        self.t = Terminal(out=self.out, cols=4, rows=2)

    def test_size_is_two_pixels_per_row(self):
        self.assertEqual(self.t.size, (4, 4))
        self.assertIn("\x1b[?25l", self.out.getvalue())   # cursor escondido

    def test_draw_and_diff(self):
        img = Image.new("RGB", (4, 4), (0, 0, 0))
        img.putpixel((0, 0), (255, 0, 0))                    # metade de cima da célula (1,1)
        img.putpixel((0, 1), (0, 255, 0))                    # metade de baixo
        self.out.truncate(0), self.out.seek(0)
        self.assertEqual(self.t.show(img), 16)
        s = self.out.getvalue()
        self.assertIn("\x1b[1;1H\x1b[38;2;255;0;0m\x1b[48;2;0;255;0m▀", s)
        self.assertEqual(s.count("▀"), 8)
        # sem mudança: nada escrito
        self.out.truncate(0), self.out.seek(0)
        self.assertEqual(self.t.show(img), 0)
        self.assertEqual(self.out.getvalue(), "")
        # um pixel muda: só aquela célula
        img.putpixel((3, 3), (1, 2, 3))
        self.assertEqual(self.t.show(img), 2)
        s = self.out.getvalue()
        self.assertTrue(s.startswith("\x1b[2;4H"))
        self.assertEqual(s.count("▀"), 1)
        self.assertIn("48;2;1;2;3m", s)

    def test_resize_redraws_everything(self):
        self.t.show(Image.new("RGB", (4, 4)))
        self.out.truncate(0), self.out.seek(0)
        self.t.show(Image.new("RGB", (6, 4)))
        self.assertEqual(self.out.getvalue().count("▀"), 12)

    def test_close_restores_cursor(self):
        self.t.close()
        self.assertTrue(self.out.getvalue().endswith("\x1b[0m\x1b[?25h\x1b[?1049l"))
        self.t.close()                                       # fechar duas vezes não quebra


if __name__ == "__main__":
    unittest.main()
