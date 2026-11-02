import _env  # noqa: F401
import os
import tempfile
import unittest

from PIL import Image

from byorzin_monitor.display.backends.framebuffer import Framebuffer


def fake_fb(w, h, bpp, stride=None):
    d = tempfile.mkdtemp(dir=_env.TMP)
    stride = stride or w * bpp // 8
    for name, val in (("virtual_size", f"{w},{h}"), ("bits_per_pixel", str(bpp)), ("stride", str(stride))):
        with open(os.path.join(d, name), "w") as f:
            f.write(val + "\n")
    dev = os.path.join(d, "fb")
    with open(dev, "wb") as f:
        f.write(bytes(stride * h))
    return dev, d


class FramebufferTest(unittest.TestCase):
    def test_rgb565(self):
        dev, sysfs = fake_fb(8, 4, 16)
        fb = Framebuffer(dev, sysfs=sysfs)
        self.assertEqual(fb.size, (8, 4))
        img = Image.new("RGB", (8, 4), (255, 0, 0))
        self.assertEqual(fb.show(img), 32)
        with open(dev, "rb") as f:
            data = f.read()
        self.assertEqual(data[:2], b"\x00\xf8")
        self.assertEqual(len(data), 8 * 4 * 2)
        img.putpixel((1, 2), (0, 0, 255))
        self.assertEqual(fb.show(img), 8)                   # só a linha 2
        with open(dev, "rb") as f:
            data = f.read()
        self.assertEqual(data[(2 * 8 + 1) * 2:(2 * 8 + 1) * 2 + 2], b"\x1f\x00")
        fb.close()

    def test_bgra_with_stride(self):
        dev, sysfs = fake_fb(3, 2, 32, stride=16)            # 4 bytes de sobra por linha
        fb = Framebuffer(dev, sysfs=sysfs)
        img = Image.new("RGB", (3, 2), (10, 20, 30))
        fb.show(img)
        with open(dev, "rb") as f:
            data = f.read()
        self.assertEqual(data[:4], bytes([30, 20, 10, 255]))
        self.assertEqual(data[12:16], bytes(4))              # preenchimento intocado
        self.assertEqual(data[16:20], bytes([30, 20, 10, 255]))
        fb.close()

    def test_bgr24(self):
        dev, sysfs = fake_fb(2, 1, 24)
        fb = Framebuffer(dev, sysfs=sysfs)
        fb.show(Image.new("RGB", (2, 1), (1, 2, 3)))
        with open(dev, "rb") as f:
            self.assertEqual(f.read(), bytes([3, 2, 1, 3, 2, 1]))
        fb.close()


if __name__ == "__main__":
    unittest.main()
