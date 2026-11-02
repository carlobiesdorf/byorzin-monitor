# Núcleo/tela: muitas sessões, emoji, 1º quadro sem a cena "limite", plurais.
import _env  # noqa: F401
import time
import unittest

from byorzin_monitor import i18n
from byorzin_monitor.display import engine as E
from byorzin_monitor.display import scenes as S
from byorzin_monitor.display.layouts import LAYOUTS


def view(n, pct=95.0):
    now = time.time()
    ss = [{"id": f"s{i}", "project": f"proj-{i}", "title": "🚀 Deploy do sistema de pagamentos ✨ em produção",
           "status": ["working", "waiting", "idle"][i % 3], "tool": "Bash", "since": now - 100, "last": now,
           "tokens": 1e6, "context_pct": 40, "mood": None,
           "subagents": [{"id": f"g{i}{j}", "type": "Explore", "tool": "Grep"} for j in range(i % 6)]} for i in range(n)]
    st = {"host": "ws", "ts": now, "sessions": ss, "events_recent": [], "last_activity": now,
          "rate": {"seen_at": now, "seven_day": {"pct": pct, "resets_at": now + 86400}}}
    return E.View([("ws", st)], {})


class FakeFetcher:
    def __init__(self, v):
        self.v, self.sources = v, [1]
        import threading
        self.lock = threading.Lock()

    def view(self, cfg):
        return self.v


class TelaTest(unittest.TestCase):
    def test_todos_os_layouts_com_muitas_sessoes(self):
        for n in (1, 4, 10, 15):
            v = view(n)
            for name, fn in LAYOUTS.items():
                im = fn(v, 1.0)
                self.assertEqual(im.size, (480, 320), (name, n))

    def test_emoji_sai_acento_fica(self):
        self.assertEqual(S.clean("🚀 Deploy ✨ ação çãõ"), "Deploy ação çãõ")
        self.assertEqual(S.clean("👍🏽 ok‍"), "ok")
        self.assertEqual(S.clean("terminou ✓"), "terminou ✓")       # a fonte tem ✓
        v = view(1)
        v.sessions[0]["title"] = "🎉🎉"
        v2 = E.View([("ws", {"host": "ws", "ts": time.time(), "sessions": [dict(v.sessions[0])], "events_recent": []})], {})
        self.assertEqual(v2.sessions[0]["label"], "proj-0")             # título só de emoji: vale o projeto

    def test_primeiro_quadro_nao_e_limite(self):
        r = E.Renderer({"port": 1, "brightness_day": 60, "brightness_night": 10}, settings=_Settings({}),
                       fetcher=FakeFetcher(view(2)))
        r.frame()
        self.assertEqual(r.mode, "work")
        r2 = E.Renderer({"port": 1}, settings=_Settings({}), fetcher=FakeFetcher(view(2)), layout="grade")
        for k in range(3):
            r2.frame(time.time() + 70 * k)
            self.assertEqual((r2.mode, r2.args[0]), ("work", "grade"))
        # sem layout forçado, o alerta aparece depois do 1º quadro
        r.frame(time.time() + 61)
        self.assertEqual(r.mode, "limit")

    def test_plurais(self):
        from byorzin_monitor.i18n import plural
        for lang, one in (("pt-BR", "+1 sessão"), ("en", "+1 session")):
            i18n.set_lang(lang)
            self.assertEqual(plural(1, "+{n} sessão", "+{n} sessões"), one)
            self.assertEqual(plural(1, "+{n} agente", "+{n} agentes"), one.replace("sessão", "agente").replace("session", "agent"))
        i18n.set_lang("en")
        self.assertEqual(i18n.T("sem sessões · agora há pouco"), "no sessions · just now")
        i18n.set_lang("pt-BR")
        v = view(0)
        v.idle_for = 10
        S.scene_idle(v, 0, "sleepy")          # não quebra; texto "agora há pouco"


class _Settings:
    def __init__(self, d):
        self.d = d

    def get(self):
        return {"layout": "cards", "brightness_day": 60, "brightness_night": 10, **self.d}


if __name__ == "__main__":
    unittest.main()
