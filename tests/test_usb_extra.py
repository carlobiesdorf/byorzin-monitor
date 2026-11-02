import _env  # noqa: F401
import struct
import unittest
from unittest import mock

from PIL import Image

from _env import FakeSerial
from byorzin_monitor.display import backends
from byorzin_monitor.display.backends.turing_b import TuringB, packet
from byorzin_monitor.display.backends.weact import WeAct, WeActMini


class TuringBTest(unittest.TestCase):
    def make(self, subrev=0x11):
        hello = bytes([0xCA]) + b"HELLO" + bytes([0x0A, subrev, 0, 0xCA])
        ser = FakeSerial(hello)
        with mock.patch("byorzin_monitor.display.backends.turing_b.BITMAP_PAUSE", 0):
            scr = TuringB(ser=ser)
        return scr, ser

    def test_packets(self):
        self.assertEqual(packet(0xCB, [1]), bytes([0xCB, 1, 0, 0, 0, 0, 0, 0, 0, 0xCB]))
        scr, ser = self.make()
        self.assertEqual(bytes(ser.out[:10]), b"\xcaHELLO\x00\x00\x00\xca")
        self.assertEqual(bytes(ser.out[10:20]), packet(0xCB, [1]))       # paisagem
        self.assertTrue(scr.analog)

    @mock.patch("byorzin_monitor.display.backends.turing_b.BITMAP_PAUSE", 0)
    def test_bitmap_big_endian(self):
        scr, ser = self.make()
        ser.out.clear()
        scr.show(Image.new("RGB", (480, 320), (255, 0, 0)))
        self.assertEqual(bytes(ser.out[:10]), bytes([0xCC, 0, 0, 0, 0, 1, 0xDF, 1, 0x3F, 0xCC]))
        self.assertEqual(bytes(ser.out[10:12]), b"\xf8\x00")            # 0xF800 big-endian
        self.assertEqual(len(ser.out), 10 + 480 * 320 * 2)
        img = Image.new("RGB", (480, 320), (255, 0, 0))
        img.putpixel((100, 50), (0, 0, 0))
        img.putpixel((300, 200), (0, 0, 0))
        ser.out.clear()
        sent = scr.show(img)                                              # um retângulo só
        self.assertEqual(ser.out.count(b"\xcc"), 2)
        self.assertEqual(sent, (304 - 96) * (208 - 48))

    def test_binary_brightness(self):
        scr, ser = self.make(subrev=0x01)
        ser.out.clear()
        scr.set_brightness(40)
        self.assertEqual(bytes(ser.out), packet(0xCE, [0]))               # 0 = aceso
        ser.out.clear()
        scr.set_brightness(0)
        self.assertEqual(bytes(ser.out), packet(0xCE, [1]))


class WeActTest(unittest.TestCase):
    def test_init_and_bitmap(self):
        ser = FakeSerial(b"\xc2V1.0.0.0" + bytes(10))
        scr = WeAct(ser=ser)
        self.assertEqual(scr.version, "V1.0.0.0")
        self.assertEqual(bytes(ser.out[:5]), b"\xc2\x0a\x02\x02\x0a")    # versão, paisagem
        ser.out.clear()
        scr.show(Image.new("RGB", (480, 320), (255, 0, 0)))
        self.assertEqual(bytes(ser.out[:10]), b"\x05" + struct.pack("<4H", 0, 0, 479, 319) + b"\x0a")
        self.assertEqual(bytes(ser.out[10:12]), b"\x00\xf8")             # little-endian
        ser.out.clear()
        scr.set_brightness(100)
        self.assertEqual(bytes(ser.out), b"\x03\xff\x00\x00\x0a")

    def test_mini_partial(self):
        scr = WeActMini(ser=FakeSerial())
        img = Image.new("RGB", (160, 80))
        scr.show(img)
        img.putpixel((5, 5), (255, 255, 255))
        self.assertEqual(scr.show(img), 16 * 16)


class Detect(unittest.TestCase):
    def port(self, vid, pid, serial):
        return mock.Mock(vid=vid, pid=pid, serial_number=serial, device="/dev/ttyACM9")

    def test_serial_picks_backend(self):
        ports = [self.port(0x1A86, 0x5722, "USB35INCHIPSV2"), self.port(0x1A86, 0x5722, "2017-2-25"),
                 self.port(0x1A86, 0xFE0C, "AD1234"), self.port(0x1A86, 0xFE0C, "AB9999"),
                 self.port(0x1234, 0x5678, "x")]
        with mock.patch("serial.tools.list_ports.comports", return_value=ports):
            found = [d["backend"] for d in backends.detect()]
        self.assertEqual(found, ["turing-a", "turing-b", "weact-096", "weact"])

    def test_every_backend_class_is_importable(self):
        import importlib
        for name, (mod, cls) in backends.BACKENDS.items():
            klass = getattr(importlib.import_module(mod), cls)
            self.assertTrue(klass.name, name)
        for _, _, _, b, label in backends.KNOWN_USB:
            self.assertIn(b, backends.BACKENDS)


if __name__ == "__main__":
    unittest.main()
