# Núcleo: máquinas com o mesmo nome, relógio, eventos fora de ordem, privacidade do hook,
# contador de tokens e histórico.
import _env  # noqa: F401
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from byorzin_monitor import collector as C
from byorzin_monitor.display import engine as E
from byorzin_monitor.history import History
from byorzin_monitor.hooks import hook


def st(host, iid=None, sessions=(), **kw):
    d = {"host": host, "ts": time.time(), "sessions": list(sessions), "events_recent": []}
    if iid:
        d["install_id"] = iid
    d.update(kw)
    return d


class DedupTest(unittest.TestCase):
    def test_mesma_instalacao_por_urls_diferentes(self):
        out = E.dedup_sources([("http://127.0.0.1:1", st("ws", "A")), ("http://192.168.1.5:1", st("ws", "A"))])
        self.assertEqual([(u, n) for u, n, _ in out], [("http://127.0.0.1:1", "ws")])

    def test_hostnames_iguais_ganham_nomes_distintos(self):
        polled = [("http://127.0.0.1:1", st("ws", "L")), ("http://10.0.0.2:1", st("raspberrypi", "P1")),
                  ("http://10.0.0.3:1", st("raspberrypi", "P2")), ("http://10.0.0.4:1", st("raspberrypi", "P3"))]
        out = E.dedup_sources(polled)
        self.assertEqual([n for _, n, _ in out], ["ws", "raspberrypi", "raspberrypi (2)", "raspberrypi (3)"])
        self.assertEqual(out[2][2]["host"], "raspberrypi (2)")          # estado usa o nome exibido
        self.assertEqual(out[2][2]["_hostname"], "raspberrypi")
        self.assertEqual(polled[2][1]["host"], "raspberrypi")            # sem mexer no original
        # estável: mesma ordem de URLs, mesmos nomes
        self.assertEqual([n for _, n, _ in E.dedup_sources(polled)], [n for _, n, _ in out])

    def test_coletor_antigo_sem_id_continua_por_hostname(self):
        out = E.dedup_sources([("http://127.0.0.1:1", st("ws")), ("http://10.0.0.9:1", st("ws"))])
        self.assertEqual(len(out), 1)

    def test_view_separa_sessoes_das_maquinas_com_mesmo_nome(self):
        s1 = {"id": "a", "project": "p1", "status": "idle", "since": 1, "last": 1, "subagents": []}
        s2 = {"id": "b", "project": "p2", "status": "working", "since": 1, "last": 1, "subagents": []}
        out = E.dedup_sources([("u1", st("pi", "1", [s1])), ("u2", st("pi", "2", [s2]))])
        v = E.View([(n, s) for _, n, s in out], {})
        self.assertEqual([h for h, _ in v.hosts], ["pi", "pi (2)"])
        self.assertEqual({s["id"]: s["host"] for s in v.sessions}, {"a": "pi", "b": "pi (2)"})
        self.assertEqual([len(m["sessions"]) for m in v.machines], [1, 1])

    def test_fetcher_usa_served_at_para_o_relogio(self):
        f = E.Fetcher.__new__(E.Fetcher)
        import threading
        f.lock, f.names, f.last_ok, f.sources, f._online, f._saved = threading.Lock(), {}, {}, [], {}, 0
        f.urls, f.token = ["http://a", "http://b"], ""
        f.live = mock.Mock(changed=lambda: None)
        now = time.time()
        # coletor com relógio 100 s adiantado; ts ficou 8 s atrás do served_at (ciclo lento)
        remote = {"http://a": st("x", "A", ts=now + 92, served_at=now + 100, last_activity=now + 50),
                  "http://b": st("x", "B", ts=now - 8, served_at=now)}
        f._get = lambda u: json.loads(json.dumps(remote[u]))
        with mock.patch.object(E.Fetcher, "_persist", lambda *a: None):
            f.poll_once()
        names = [n for n, _ in f.sources]
        self.assertEqual(names, ["x", "x (2)"])
        a = f.sources[0][1]
        self.assertAlmostEqual(a["last_activity"], now - 50, delta=1.5)
        self.assertAlmostEqual(a["ts"], now - 8, delta=1.5)
        self.assertAlmostEqual(f.sources[1][1]["ts"], now - 8, delta=0.5)   # sem diferença: não mexe


class EventOrderTest(unittest.TestCase):
    def setUp(self):
        self.es = C.EventState()

    def ap(self, name, ts, **kw):
        self.es.apply({"session_id": "S", "hook_event_name": name, "ts": ts, **kw})

    def test_evento_atrasado_nao_desfaz_status(self):
        self.ap("PreToolUse", 10, tool_name="Bash")
        self.ap("Stop", 12)
        self.ap("PostToolUse", 11)          # chegou depois do Stop, mas é anterior
        self.assertEqual(self.es.sess["S"]["status"], "idle")
        self.ap("PermissionRequest", 13)
        self.ap("PreToolUse", 12.5, tool_name="Edit")
        self.assertEqual(self.es.sess["S"]["status"], "waiting")

    def test_tombstone_de_subagente(self):
        self.ap("SubagentStart", 10, agent_id="g1", agent_type="Explore")
        self.ap("SubagentStop", 20, agent_id="g1")
        self.ap("PreToolUse", 15, agent_id="g1", tool_name="Grep")       # atrasado
        self.ap("PostToolUse", 16, agent_id="g1")
        self.assertNotIn("g1", self.es.sess["S"]["subagents"])

    def test_evento_do_agente_antes_do_start(self):
        self.ap("PreToolUse", 11, agent_id="g2", agent_type="Plan", tool_name="Read")
        self.ap("SubagentStart", 10, agent_id="g2", agent_type="Plan")
        sub = self.es.sess["S"]["subagents"]["g2"]
        self.assertEqual((sub["tool"], sub["type"], sub["last"]), ("Read", "Plan", 11))

    def test_subagente_sem_stop_expira(self):
        self.ap("SubagentStart", time.time() - C.SUBAGENT_STALE - 5, agent_id="velho")
        subs = [a for a, s in self.es.sess["S"]["subagents"].items() if time.time() - s["last"] < C.SUBAGENT_STALE]
        self.assertEqual(subs, [])

    def test_sessao_encerrada_nao_volta(self):
        self.ap("PreToolUse", 10, tool_name="Bash")
        self.ap("SessionEnd", 20)
        self.ap("PostToolUse", 15)
        self.assertNotIn("S", self.es.sess)
        self.ap("SessionStart", 30)          # retomada depois: volta
        self.assertIn("S", self.es.sess)


class SubagentPermissionTest(unittest.TestCase):
    def test_permissao_dentro_de_subagente(self):
        es = C.EventState()
        ap = lambda name, ts, **kw: es.apply({"session_id": "S", "hook_event_name": name, "ts": ts, **kw})
        ap("PreToolUse", 1, tool_name="Agent")
        ap("SubagentStart", 2, agent_id="g", agent_type="Explore")
        ap("PreToolUse", 3, agent_id="g", tool_name="Bash")
        ap("PermissionRequest", 4, agent_id="g", tool_name="Bash")
        s = es.sess["S"]
        self.assertEqual(s["status"], "waiting")
        self.assertIsNone(s["tool"])                     # a ferramenta do agente não vira da sessão
        self.assertTrue(s["subagents"]["g"]["waiting"])
        ap("PostToolUse", 6, agent_id="g", tool_name="Bash")    # você respondeu, o agente seguiu
        self.assertEqual((s["status"], s["tool"]), ("working", "Agent"))
        self.assertFalse(s["subagents"]["g"]["waiting"])

    def test_notification_de_subagente(self):
        es = C.EventState()
        es.apply({"session_id": "S", "hook_event_name": "Stop", "ts": 1})
        es.apply({"session_id": "S", "hook_event_name": "Notification", "ts": 2, "agent_id": "g",
                  "notification_type": "permission_prompt"})
        self.assertEqual(es.sess["S"]["status"], "waiting")
        es.apply({"session_id": "S", "hook_event_name": "SubagentStop", "ts": 3, "agent_id": "g"})
        self.assertEqual(es.sess["S"]["status"], "idle")


class HookPrivacyTest(unittest.TestCase):
    def test_erro_de_ferramenta_nao_e_gravado(self):
        ev = hook.event({"session_id": "s", "hook_event_name": "PostToolUseFailure", "tool_name": "Read",
                         "error": "ENOENT: /home/fulano/segredos/senhas.txt", "cwd": "/home/fulano/proj"})
        self.assertNotIn("error", ev)
        self.assertNotIn("fulano", json.dumps(ev))
        self.assertEqual(ev["project"], "proj")

    def test_stopfailure_so_lista_conhecida(self):
        ok = hook.event({"session_id": "s", "hook_event_name": "StopFailure", "error": "rate_limit"})
        self.assertEqual(ok["error"], "rate_limit")
        d = hook.event({"session_id": "s", "hook_event_name": "StopFailure", "error": {"type": "overloaded"}})
        self.assertEqual(d["error"], "overloaded")
        other = hook.event({"session_id": "s", "hook_event_name": "StopFailure", "error": "texto livre /tmp/x"})
        self.assertEqual(other["error"], "other")

    def test_campos_livres_so_de_listas(self):
        ev = hook.event({"session_id": "s", "hook_event_name": "SessionEnd", "reason": "meu motivo secreto",
                         "source": "startup", "notification_type": "idle_prompt", "prompt": "não grave",
                         "tool_input": {"command": "rm -rf"}, "message": "oi"})
        self.assertEqual((ev["reason"], ev["source"], ev["notification_type"]), ("other", "startup", "idle_prompt"))
        for k in ("prompt", "tool_input", "message"):
            self.assertNotIn(k, ev)


class TokenCounterTest(unittest.TestCase):
    def setUp(self):
        self.tok_file = Path(tempfile.mkdtemp(dir=_env.TMP)) / "tokens.json"
        self.p = mock.patch.object(C, "TOKENS_FILE", self.tok_file)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_seen_mantem_os_mais_recentes(self):
        tc = C.TokenCounter()
        with mock.patch.object(C, "SEEN_MAX", 5):
            for i in range(12):
                tc.seen[f"m{i}"] = None
            tc.save()
        saved = json.loads(self.tok_file.read_text())["seen"]
        self.assertEqual(saved, [f"m{i}" for i in range(7, 12)])
        self.assertEqual(list(C.TokenCounter().seen), saved)

    def test_le_em_blocos_e_poda_offsets(self):
        proj = C.CLAUDE_DIR / "projects" / "tc-teste"
        proj.mkdir(parents=True, exist_ok=True)
        f = proj / "sess-tc.jsonl"
        ts = datetime.now().astimezone().isoformat()
        lines = [json.dumps({"type": "assistant", "sessionId": "sess-tc", "requestId": f"r{i}", "timestamp": ts,
                             "message": {"id": f"m{i}", "model": "claude-x", "usage": {"input_tokens": 10, "output_tokens": 5}},
                             "pad": "x" * 300}) for i in range(40)]
        f.write_text("\n".join(lines) + "\n")
        tc = C.TokenCounter()
        tc.offsets[str(proj / "sumiu.jsonl")] = 123
        with mock.patch.object(C, "READ_BLOCK", 1000):
            tc.scan()
        self.assertEqual(tc.sessions["sess-tc"], 40 * 15)
        self.assertEqual(tc.offsets[str(f)], f.stat().st_size)
        self.assertNotIn(str(proj / "sumiu.jsonl"), tc.offsets)
        with open(f, "a") as fh:      # linha pela metade: só conta quando terminar
            fh.write(lines[0].replace("m0", "m99").replace("r0", "r99")[:50])
        tc.scan()
        self.assertEqual(tc.sessions["sess-tc"], 40 * 15)
        f.unlink()


class FakeTC:
    def __init__(self):
        self.hours, self.models, self.days = {}, {}, {}

    def add(self, ts, n, model="opus"):
        h = int(ts // 3600 * 3600)
        b = self.hours.setdefault(h, {"tot": 0, "out": 0})
        b["tot"] += n
        mb = self.models.setdefault(h, {})
        mb[model] = mb.get(model, 0) + n
        day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        self.days[day] = self.days.get(day, 0) + n


class HistoryRolloverTest(unittest.TestCase):
    def test_instalacao_nova_e_virada_de_dia(self):
        d0 = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0) - timedelta(days=3)
        clock = [d0.timestamp()]
        h = History(path=Path(tempfile.mkdtemp(dir=_env.TMP)) / "h.json", clock=lambda: clock[0])
        tc = FakeTC()
        day0 = d0.strftime("%Y-%m-%d")
        tc.add(d0.timestamp(), 300_000)
        h.on_event({"session_id": "s", "hook_event_name": "UserPromptSubmit", "ts": d0.timestamp()})
        h.sync_tokens(tc)
        self.assertEqual(h.days[day0]["tokens"], 300_000)
        # mais tokens no mesmo dia (1º dia, parcial): o histórico acompanha, sem contar em dobro
        clock[0] += 3 * 3600
        tc.add(clock[0], 200_000, "sonnet")
        h.sync_tokens(tc)
        h.sync_tokens(tc)
        self.assertEqual(h.days[day0]["tokens"], 500_000)
        self.assertEqual(h.days[day0]["models"], {"opus": 300_000, "sonnet": 200_000})
        # virada do dia
        clock[0] = (d0 + timedelta(days=1)).replace(hour=0, minute=30).timestamp()
        tc.add(clock[0], 70_000)
        h.sync_tokens(tc)
        day1 = (d0 + timedelta(days=1)).strftime("%Y-%m-%d")
        self.assertEqual(h.days[day0]["tokens"], 500_000)
        self.assertEqual(h.days[day1]["tokens"], 70_000)
        clock[0] += 3600
        tc.add(clock[0], 30_000)
        h.sync_tokens(tc)
        self.assertEqual(h.days[day1]["tokens"], 100_000)
        self.assertEqual(h.export(5)[day1]["models"], {"opus": 100_000})

    def test_dia_parcial_da_janela_nao_diminui(self):
        now = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        h = History(path=Path(tempfile.mkdtemp(dir=_env.TMP)) / "h.json", clock=lambda: now.timestamp())
        old = (now - timedelta(days=8)).strftime("%Y-%m-%d")      # começa antes da janela de 8 dias
        h._d(old).update(tokens=900, models={"opus": 900})
        tc = FakeTC()
        tc.add((now - timedelta(days=8)).replace(hour=20).timestamp(), 100)   # sobrou só um pedaço nos baldes
        tc.days[old] = 900
        h.sync_tokens(tc)
        self.assertEqual(h.days[old]["tokens"], 900)
        self.assertEqual(h.days[old]["models"], {"opus": 900})


class HostMetricsTest(unittest.TestCase):
    def test_usa_ollama_url_do_config(self):
        hm = C.HostMetrics("http://10.9.9.9:1234/")
        seen = []

        def fake(url, timeout=None):
            seen.append(url)
            raise OSError("sem rede")
        with mock.patch.object(C.urllib.request, "urlopen", fake), mock.patch.object(C.shutil, "which", lambda *_: None):
            hm.collect()
        self.assertEqual(seen, ["http://10.9.9.9:1234/api/ps"])


if __name__ == "__main__":
    unittest.main()
