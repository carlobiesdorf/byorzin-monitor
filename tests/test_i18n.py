# Idioma da tela e cor padrão das máquinas.
import _env  # noqa: F401
import unittest

from byorzin_monitor import i18n
from byorzin_monitor.display import scenes as S
from byorzin_monitor.display.demo import demo_view
from byorzin_monitor.display.layouts import LAYOUTS
from byorzin_monitor.settings import validate


class TestI18n(unittest.TestCase):
    def tearDown(self):
        i18n.set_lang("pt-BR")

    def test_traducao_e_formatacao(self):
        i18n.set_lang("en")
        self.assertEqual(i18n.T("esperando você"), "waiting for you")
        self.assertEqual(i18n.T("ocioso há {d}", d="5 min"), "idle for 5 min")
        self.assertEqual(S.fmt_tok(2.15e6), "2.1M")
        self.assertEqual(i18n.day_month("2026-10-14"), "10/14")
        i18n.set_lang("pt-BR")
        self.assertEqual(i18n.T("ocioso há {d}", d="5 min"), "ocioso há 5 min")
        self.assertEqual(S.fmt_tok(2.15e6), "2,1M")
        self.assertEqual(i18n.day_month("2026-10-14"), "14/10")

    def test_sem_traducao_cai_no_ptbr(self):
        i18n.set_lang("en")
        self.assertEqual(i18n.T("texto sem tradução"), "texto sem tradução")

    def test_layouts_nos_dois_idiomas(self):
        for lang in ("en", "pt-BR"):
            i18n.set_lang(lang)
            v = demo_view({})
            for name, fn in LAYOUTS.items():
                im = fn(v, 1.0)
                self.assertEqual(im.size, (S.W, S.H), (lang, name))

    def test_ajuste_language(self):
        self.assertEqual(validate({})["language"], "pt-BR")
        self.assertEqual(validate({"language": "en"})["language"], "en")
        self.assertEqual(validate({"language": "xx"})["language"], "pt-BR")


class TestCores(unittest.TestCase):
    def tearDown(self):
        S.set_colors({})

    def test_cor_deterministica(self):
        self.assertEqual(S.PALETTE[0], "#39ff88")
        a = S.default_color("workstation")
        self.assertIn(a, S.PALETTE)
        self.assertEqual(a, S.default_color("workstation"))
        self.assertEqual(S.host_color("workstation")[0], a)

    def test_cor_do_painel_tem_prioridade(self):
        S.set_colors({"server": "#123456"})
        self.assertEqual(S.host_color("server")[0], "#123456")


if __name__ == "__main__":
    unittest.main()
