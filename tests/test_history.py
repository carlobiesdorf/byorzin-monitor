import _env
import unittest
from datetime import datetime

from byorzin_monitor.history import History, tool_key


def ts_of(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").timestamp()


def ev(name, when, sid="s1", **kw):
    return {"session_id": sid, "hook_event_name": name, "ts": ts_of(when), **kw}


class FakeTokens:
    def __init__(self, hours, models, days=None):
        self.hours, self.models, self.days = hours, models, days or {}


class TestHistory(unittest.TestCase):
    def setUp(self):
        self.path = _env.TMP / f"hist-{self.id()}.json"
        self.now = ts_of("2026-03-10 12:00:00")
        self.h = History(self.path, clock=lambda: self.now)

    def test_contagens_e_releitura(self):
        evs = [ev("SessionStart", "2026-03-10 09:00:00"), ev("UserPromptSubmit", "2026-03-10 09:00:01"),
               ev("PreToolUse", "2026-03-10 09:00:05", tool_name="Bash"),
               ev("PreToolUse", "2026-03-10 09:00:09", tool_name="mcp__github__create_issue"),
               ev("SubagentStart", "2026-03-10 09:00:10", agent_type="Explore", agent_id="a1"),
               ev("PreToolUse", "2026-03-10 09:00:20", tool_name="Bash", agent_id="a1"),
               ev("Stop", "2026-03-10 09:01:01"),
               ev("SessionStart", "2026-03-10 10:00:00", sid="s2")]
        for e in evs:
            self.h.on_event(e)
        for e in evs:                 # coletor reiniciou e releu o events.jsonl
            self.h.on_event(e)
        d = self.h.export(7)["2026-03-10"]
        self.assertEqual(d["sessions"], 2)
        self.assertEqual(d["tools"], {"Bash": 2, "mcp:github": 1})
        self.assertEqual(d["agents"], {"Explore": 1})
        self.assertEqual(d["prompts"], 1)
        self.assertEqual(d["work_s"], 60)
        self.h.save(force=True)
        h2 = History(self.path, clock=lambda: self.now)
        self.assertEqual(h2.export(7)["2026-03-10"]["tools"]["Bash"], 2)
        h2.on_event(evs[2])           # depois de recarregar também não conta de novo
        self.assertEqual(h2.export(7)["2026-03-10"]["tools"]["Bash"], 2)

    def test_virada_de_dia(self):
        self.h.on_event(ev("UserPromptSubmit", "2026-03-09 23:55:00"))
        self.h.on_event(ev("PreToolUse", "2026-03-10 00:05:00", tool_name="Read"))
        self.h.on_event(ev("Stop", "2026-03-10 00:06:00"))
        x = self.h.export(7)
        self.assertEqual(x["2026-03-09"]["work_s"], 300)
        self.assertEqual(x["2026-03-10"]["work_s"], 360)
        self.assertEqual(x["2026-03-10"]["tools"], {"Read": 1})
        self.assertEqual(x["2026-03-09"]["sessions"], 1)
        self.assertEqual(x["2026-03-10"]["sessions"], 1)

    def test_buraco_grande_nao_conta(self):
        self.h.on_event(ev("UserPromptSubmit", "2026-03-10 08:00:00"))
        self.h.on_event(ev("PostToolUse", "2026-03-10 09:00:00"))
        self.assertEqual(self.h.export(1)["2026-03-10"]["work_s"], 0)

    def test_tokens_e_poda(self):
        h0 = ts_of("2026-03-09 00:00:00")
        hours = {int(h0): {"tot": 100, "out": 1}, int(h0 + 3600): {"tot": 50, "out": 1},
                 int(ts_of("2026-03-10 10:00:00")): {"tot": 7, "out": 0}}
        models = {int(h0): {"opus-5": 100}, int(h0 + 3600): {"sonnet-5": 50}}
        self.h.days["2025-01-01"] = {"tokens": 1, "models": {}, "sids": [], "tools": {}, "agents": {}, "work_s": 0, "prompts": 0}
        self.h.sync_tokens(FakeTokens(hours, models, {"2026-03-01": 999, "2026-03-09": 150}))
        x = self.h.export(30)
        self.assertEqual(x["2026-03-09"]["tokens"], 150)
        self.assertEqual(x["2026-03-09"]["models"], {"opus-5": 100, "sonnet-5": 50})
        self.assertEqual(x["2026-03-10"]["tokens"], 7)
        self.assertEqual(x["2026-03-01"]["tokens"], 999)       # dia antigo vem do total do TokenCounter
        self.h.save(force=True)
        self.assertNotIn("2025-01-01", self.h.days)           # mais de 90 dias: sai

    def test_tool_key(self):
        self.assertEqual(tool_key("mcp__claude-in-chrome__navigate"), "mcp:claude-in-chrome")
        self.assertEqual(tool_key("Edit"), "Edit")


if __name__ == "__main__":
    unittest.main()
