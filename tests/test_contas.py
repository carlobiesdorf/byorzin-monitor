# Várias contas do Claude: identidade da conta (sem vazar e-mail/uuid), limites por conta no
# rate.json e no /state, compatibilidade com coletores antigos, tela igual com uma conta só,
# barras por conta sem sobreposição, alerta de limite por conta e rótulos editáveis.
import _env  # noqa: F401
import io
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest import mock

import hd_frames
from byorzin_monitor import account as A
from byorzin_monitor.common import RATE_FILE, SESSION_INFO_DIR
from byorzin_monitor.display import demo as D
from byorzin_monitor.display import engine as E
from byorzin_monitor.display import layouts as L
from byorzin_monitor.display import scenes as S
from byorzin_monitor.hooks import statusline
from byorzin_monitor.settings import validate

EMAIL = "ana.souza@exemplo.com"
UUID = "6f1c0d6e-9a1b-4c2d-8e3f-0123456789ab"


def oauth(uuid=UUID, org="org-1", name="Ana Souza", org_name=None, org_type="claude_max", email=EMAIL):
    return {"oauthAccount": {"accountUuid": uuid, "organizationUuid": org, "displayName": name, "emailAddress": email,
                             "organizationName": org_name or f"{email}'s Organization", "organizationType": org_type,
                             "billingType": "stripe_subscription"}}


_bump = [0]


def write_claude_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data))
    _bump[0] += 1
    t = time.time() + _bump[0]          # mtime sempre diferente: o cache por mtime percebe a troca
    os.utime(path, ns=(int(t * 1e9), int(t * 1e9)))


def reset_cache():
    A._MEM.update(sig=None, acc=None)
    try:
        A.CACHE_FILE.unlink()
    except FileNotFoundError:
        pass


@contextmanager
def claude_dir(data=None, home_data=None):
    """CLAUDE_CONFIG_DIR e HOME falsos, cada um com (ou sem) .claude.json."""
    with tempfile.TemporaryDirectory(dir=_env.TMP) as cd, tempfile.TemporaryDirectory(dir=_env.TMP) as home:
        if data is not None:
            write_claude_json(Path(cd) / ".claude.json", data)
        if home_data is not None:
            write_claude_json(Path(home) / ".claude.json", home_data)
        reset_cache()
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": cd}), mock.patch("pathlib.Path.home", return_value=Path(home)):
            yield Path(cd)
        reset_cache()


def run_statusline(payload):
    with redirect_stdout(io.StringIO()):
        statusline._save(payload, time.time())


def rl(week, five, wr=None, fr=None):
    now = time.time()
    return {"seven_day": {"used_percentage": week, "resets_at": wr or now + 3 * 86400},
            "five_hour": {"used_percentage": five, "resets_at": fr or now + 3 * 3600}}


# ---------------------------------------------------------------- identidade
class Identidade(unittest.TestCase):
    def test_oauth_pessoal(self):
        acc = A.parse(oauth())
        self.assertRegex(acc["id"], r"^[0-9a-f]{12}$")
        self.assertEqual(acc["label"], "Ana")                  # primeiro nome, nunca a organização com e-mail
        self.assertNotIn(UUID[:8], acc["id"])

    def test_organizacao_de_equipe(self):
        self.assertEqual(A.parse(oauth(org_name="Empresa X", org_type="claude_team"))["label"], "Empresa X")
        self.assertEqual(A.parse(oauth(org_name="Grande SA", org_type="claude_enterprise"))["label"], "Grande SA")
        # organização "de equipe" com @ no nome cai no primeiro nome
        self.assertEqual(A.parse(oauth(org_name="x@y.com", org_type="claude_team"))["label"], "Ana")

    def test_sem_nome_usa_hash(self):
        acc = A.parse(oauth(name=EMAIL))
        self.assertEqual(acc["label"], f"conta-{acc['id'][:4]}")
        acc = A.parse(oauth(name=None))
        self.assertTrue(acc["label"].startswith("conta-"))

    def test_mesma_pessoa_outra_organizacao_e_outra_conta(self):
        self.assertNotEqual(A.parse(oauth(org="o1"))["id"], A.parse(oauth(org="o2"))["id"])
        self.assertEqual(A.parse(oauth(org="o1"))["id"], A.parse(oauth(org="o1", name="Outro"))["id"])

    def test_api_key(self):
        for data in ({}, {"oauthAccount": None}, {"oauthAccount": {"accountUuid": ""}}, [], "x"):
            self.assertEqual(A.parse(data), {"id": "api", "label": "API key"}, data)

    def test_arquivo_ausente_ou_invalido(self):
        with claude_dir():
            self.assertEqual(A.identify()["id"], "api")
        with claude_dir("{isto não é json"):
            self.assertEqual(A.identify()["id"], "api")

    def test_prefere_claude_config_dir(self):
        with claude_dir(oauth(uuid="aaa"), home_data=oauth(uuid="bbb")):
            self.assertEqual(A.identify()["id"], A.parse(oauth(uuid="aaa"))["id"])
        with claude_dir(None, home_data=oauth(uuid="bbb")):      # CLAUDE_CONFIG_DIR sem o arquivo: ~/.claude.json
            self.assertEqual(A.identify()["id"], A.parse(oauth(uuid="bbb"))["id"])

    def test_cache_por_mtime(self):
        with claude_dir(oauth(uuid="aaa")) as cd:
            a = A.identify()
            with mock.patch.object(A, "parse", side_effect=AssertionError("releu sem mudar")):
                self.assertEqual(A.identify(), a)                # memória
                A._MEM.update(sig=None, acc=None)
                self.assertEqual(A.identify(), a)                # arquivo de cache (outro processo)
            write_claude_json(cd / ".claude.json", oauth(uuid="ccc"))   # /login em outra conta
            self.assertEqual(A.identify()["id"], A.parse(oauth(uuid="ccc"))["id"])
            self.assertNotIn(EMAIL, A.CACHE_FILE.read_text())

    def test_rotulo_limpo(self):
        self.assertEqual(A.clean_label("  Pes\x00soal\n "), "Pes soal")
        self.assertIsNone(A.clean_label("\x07\n"))
        self.assertEqual(len(A.clean_label("x" * 100)), A.LABEL_MAX)


# ---------------------------------------------------------------- rate.json e /state
class RatePorConta(unittest.TestCase):
    def setUp(self):
        for p in [RATE_FILE] + list(SESSION_INFO_DIR.glob("*.json")):
            try:
                p.unlink()
            except FileNotFoundError:
                pass

    def accounts(self):
        return json.loads(RATE_FILE.read_text())["accounts"]

    def test_por_conta_e_monotonico_por_janela(self):
        wr = time.time() + 3 * 86400
        with claude_dir(oauth(uuid="aaa")) as cd:
            a = A.identify()["id"]
            run_statusline({"session_id": "s1", "rate_limits": rl(50, 10, wr)})
            run_statusline({"session_id": "s2", "rate_limits": rl(40, 5, wr)})     # sessão parada, valor velho
            self.assertEqual(self.accounts()[a]["seven_day"]["pct"], 50)
            write_claude_json(cd / ".claude.json", oauth(uuid="bbb", name="Bia Lima"))
            b = A.identify()["id"]
            run_statusline({"session_id": "s3", "rate_limits": rl(7, 3, wr)})       # outra conta: janela própria
            accs = self.accounts()
            self.assertEqual(accs[a]["seven_day"]["pct"], 50)
            self.assertEqual(accs[b]["seven_day"]["pct"], 7)
            self.assertEqual(accs[b]["label"], "Bia")
            # janela nova da conta A (resets_at maior) vale mesmo com uso menor
            write_claude_json(cd / ".claude.json", oauth(uuid="aaa"))
            run_statusline({"session_id": "s1", "rate_limits": rl(2, 1, wr + 7 * 86400)})
            self.assertEqual(self.accounts()[a]["seven_day"]["pct"], 2)
            self.assertEqual(json.loads((SESSION_INFO_DIR / "s3.json").read_text())["account"], b)
            raw = RATE_FILE.read_text()
            self.assertNotIn(EMAIL, raw)
            self.assertNotIn("aaa", raw.replace(a, "").replace(b, ""))

    def test_le_formato_antigo(self):
        old = {"seen_at": time.time(), "seven_day": {"pct": 61.0, "resets_at": time.time() + 86400}}
        RATE_FILE.write_text(json.dumps(old))
        with claude_dir(oauth()):
            a = A.identify()["id"]
            self.assertEqual(A.rate_accounts(old, a), {a: old})
            run_statusline({"session_id": "s1", "rate_limits": rl(30, 5, old["seven_day"]["resets_at"])})
            self.assertEqual(self.accounts()[a]["seven_day"]["pct"], 61)     # mesma janela: não desce

    def test_api_key_sem_limites(self):
        with claude_dir({}):
            run_statusline({"session_id": "s1", "model": {"display_name": "Opus"}})
            self.assertFalse(RATE_FILE.exists())
            self.assertEqual(json.loads((SESSION_INFO_DIR / "s1.json").read_text())["account"], "api")

    def test_state_sem_dados_pessoais_e_compativel(self):
        from byorzin_monitor.collector import Collector
        with claude_dir(oauth(org_name="Empresa X", org_type="claude_team")):
            run_statusline({"session_id": "s1", "rate_limits": rl(44, 12)})
            col = Collector({"hostname": "maq-teste"})
            col.build()
            st = col.state
            body = json.dumps(st)
            for secret in (EMAIL, UUID, "Souza", "org-1"):
                self.assertNotIn(secret, body)
            a = st["account"]
            self.assertEqual(a["label"], "Empresa X")
            self.assertEqual(set(st["rates"]), {a["id"]})
            self.assertEqual(st["rate"], st["rates"][a["id"]])     # campo antigo para peers antigos
            self.assertEqual(st["rate"]["seven_day"]["pct"], 44)


# ---------------------------------------------------------------- visão (engine)
def src(host, rate=None, account=None, rates=None, sessions=()):
    st = {"host": host, "ts": time.time(), "sessions": [dict(s) for s in sessions], "tokens": {}, "events_recent": [],
          "last_activity": time.time()}
    if rate is not None:
        st["rate"] = rate
    if account is not None:
        st["account"] = account
    if rates is not None:
        st["rates"] = rates
    return st


def snap(week, five, wr=1e10, fr=1e10 - 1, label=None):
    s = {"seen_at": time.time(), "seven_day": {"pct": week, "resets_at": wr}, "five_hour": {"pct": five, "resets_at": fr}}
    if label:
        s["label"] = label
    return s


def sess(sid, account=None):
    s = {"id": sid, "project": sid, "status": "working", "tool": "Bash", "since": time.time() - 60, "last": time.time(),
         "subagents": []}
    if account:
        s["account"] = account
    return s


AID, BID = "aaaaaaaaaaaa", "bbbbbbbbbbbb"


class Visao(unittest.TestCase):
    def test_peers_antigos_como_antes(self):
        v = E.View([("a", src("a", snap(40, 10, wr=2e10))), ("b", src("b", snap(70, 5)))])
        self.assertFalse(v.multi_account)
        self.assertEqual((v.week_pct, v.five_hour), (40, 10))      # janela mais nova vale: _best de sempre
        v = E.View([("a", src("a", snap(40, 10, wr=1e10))), ("b", src("b", snap(70, 5, wr=1e10)))])
        self.assertEqual(v.week_pct, 70)

    def test_peer_antigo_mais_um_novo_viram_uma_conta(self):
        new = src("a", snap(40, 10, 5e9, 5e9), {"id": AID, "label": "Ana"}, {AID: snap(40, 10, 5e9, 5e9)})
        old = src("b", snap(55, 20, 5e9, 5e9))
        v = E.View([("a", new), ("b", old)])
        self.assertEqual(len(v.accounts), 1)
        self.assertFalse(v.multi_account)
        self.assertEqual((v.week_pct, v.five_hour), (55, 20))

    def test_duas_contas(self):
        a = src("note", snap(83, 92, 5e9, 5e9), {"id": AID, "label": "Pessoal"}, {AID: snap(83, 92, 5e9, 5e9)},
                [sess("s1", AID)])
        b = src("srv", snap(41, 20, 6e9, 6e9), {"id": BID, "label": "Trabalho"}, {BID: snap(41, 20, 6e9, 6e9)},
                [sess("s2", BID)])
        old = src("velho", snap(50, 30, 6e9, 6e9))          # coletor antigo: mesma janela da conta Trabalho
        v = E.View([("note", a), ("srv", b), ("velho", old)], {"account_labels": {BID: "Empresa"}})
        self.assertTrue(v.multi_account)
        self.assertEqual([x["label"] for x in v.accounts], ["Empresa", "Pessoal"])
        emp = v.accounts[0]
        self.assertEqual((emp["week_pct"], emp["five_hour"]), (50, 30))   # mesclou o antigo pela janela
        self.assertEqual((v.week_pct, v.five_hour), (83, 92))             # números gerais = a mais apertada
        self.assertEqual(v.limit_account["label"], "Pessoal")
        self.assertEqual({s["id"]: s["account_label"] for s in v.sessions}, {"s1": "Pessoal", "s2": "Empresa"})
        self.assertEqual(v.fat, 0.83)

    def test_uma_conta_sem_marcador_nas_sessoes(self):
        a = src("note", None, {"id": AID, "label": "Ana"}, {AID: snap(10, 5)}, [sess("s1", AID)])
        b = src("srv", None, {"id": AID, "label": "Ana"}, {AID: snap(12, 4)}, [sess("s2", AID)])
        v = E.View([("note", a), ("srv", b)])
        self.assertFalse(v.multi_account)
        self.assertTrue(all("account_label" not in s for s in v.sessions))

    def test_unskew_das_contas(self):
        st = src("a", snap(1, 1), {"id": AID, "label": "x"}, {AID: snap(1, 1)})
        seen = st["rates"][AID]["seen_at"]
        E._unskew(st, 100)
        self.assertAlmostEqual(st["rates"][AID]["seen_at"], seen + 100)

    def test_marcadores_unicos(self):
        self.assertEqual(E.account_tags(["Pessoal", "Trabalho"]), ["P", "T"])
        self.assertEqual(E.account_tags(["Pessoal", "Projeto", "Trabalho"]), ["Pe", "Pr", "T"])
        self.assertEqual(E.account_tags(["Ana", "Ana"]), ["1", "2"])


# ---------------------------------------------------------------- tela
class Recorder:
    """ImageDraw que anota as caixas de texto desenhadas (para achar sobreposição)."""

    def __init__(self, d, log):
        self.d, self.log = d, log

    def text(self, xy, text, font=None, **kw):
        x, y = xy
        k = S.scale()
        x0, y0, x1, y1 = font.getbbox(text)
        self.log.append((text, x + x0 / k, y + y0 / k, x + x1 / k, y + y1 / k))
        self.d.text(xy, text, font=font, **kw)

    def __getattr__(self, n):
        return getattr(self.d, n)


@contextmanager
def recording():
    log = []
    real = S.Draw
    with mock.patch.object(S, "Draw", lambda im: Recorder(real(im), log)):
        yield log


def overlaps(boxes):
    bad = []
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            if a[1] < b[3] - 1 and b[1] < a[3] - 1 and a[2] < b[4] - 1 and b[2] < a[4] - 1:
                bad.append((a[0], b[0]))
    return bad


class Tela(unittest.TestCase):
    # referência de pixels gerada no Linux (ver test_hd.py): no macOS o cairo do Homebrew difere
    @unittest.skipUnless(sys.platform == "linux", "referência gerada no Linux")
    def test_uma_conta_mesma_tela(self):
        """Com uma conta no formato novo (account/rates), os quadros batem com os hashes de antes."""
        from test_hd import GOLDEN

        def one_account(sources, settings=None):
            out = []
            for n, st in sources:
                if not st.get("_offline"):
                    st = {**st, "account": {"id": AID, "label": "Ana"}, "rates": {AID: st["rate"]}}
                    st["sessions"] = [{**s, "account": AID} for s in st["sessions"]]
                out.append((n, st))
            return E.View(out, settings)
        with mock.patch.object(D, "View", one_account):
            self.assertTrue(D.demo_view({}).accounts[0]["id"] == AID)
            self.assertEqual(hd_frames.digests(), GOLDEN)

    def frames(self, n):
        def v():
            L._Focus.idx, L._Focus.until = 0, 0
            return D.demo_view({}, accounts=n)
        out = {f"layout-{k}": (lambda f=f: f(v(), 3.0)) for k, f in L.LAYOUTS.items()}
        out.update({"limit": lambda: S.scene_limit(v(), 3.0), "awake": lambda: S.scene_idle(v(), 3.0, "awake"),
                    "sleep": lambda: S.scene_idle(v(), 3.0, "sleep"), "host": lambda: S.scene_host(v(), 3.0, *v().metrics[0])})
        return out

    def test_varias_contas_sem_sobreposicao(self):
        for lang in ("pt-BR", "en"):
            for n in (2, 3, 4):
                for k in (1, 2):
                    with hd_frames.frozen(), recording() as log:
                        from byorzin_monitor import i18n
                        i18n.set_lang(lang)
                        for name, f in self.frames(n).items():
                            del log[:]
                            with S.scaled(k):
                                im = f()
                            self.assertEqual(im.size, (480 * k, 320 * k), name)
                            # barra de cima e rodapés: nada por cima de nada, nada para fora da tela
                            foot = 228 if name == "limit" else 290
                            for zone in ([b for b in log if b[4] <= 27], [b for b in log if b[2] >= foot]):
                                self.assertEqual(overlaps(zone), [], (lang, n, k, name))
                                for b in zone:
                                    self.assertLessEqual(b[3], 481, (lang, n, k, name, b))

    def test_rotulos_de_todas_as_contas_no_rodape(self):
        with hd_frames.frozen(), recording() as log:
            L.layout_cards(D.demo_view({}, accounts=3), 1.0)
            texts = [b[0] for b in log]
            for lab in ("Trabalho", "Pessoal", "Cliente"):
                self.assertIn(lab, texts)
            del log[:]
            L.layout_cards(D.demo_view({}, accounts=4), 1.0)
            texts = [b[0] for b in log]
            self.assertIn("+2", texts)                       # 4 contas: as 2 mais altas + "+2"
            self.assertIn("Pessoal", texts)

    def test_alerta_de_limite_por_conta(self):
        v = D.demo_view({}, accounts=2)                  # Pessoal: 5h em 92%
        d = E.Director()
        now = time.time()
        cfg = {"limit_alert_pct": 90}
        d.pick(v, cfg, now)
        self.assertEqual(d.pick(v, cfg, now + 61), ("limit", ()))
        with hd_frames.frozen(), recording() as log:
            S.scene_limit(v, 1.0)
            self.assertIn("conta Pessoal", [b[0] for b in log])
        # nenhuma conta passou do limiar: sem alerta (mesmo somando as contas daria mais)
        a = src("a", None, {"id": AID, "label": "A"}, {AID: snap(60, 50)}, [sess("s1", AID)])
        b = src("b", None, {"id": BID, "label": "B"}, {BID: snap(70, 45)}, [sess("s2", BID)])
        v = E.View([("a", a), ("b", b)])
        d = E.Director()
        d.pick(v, cfg, now)
        self.assertEqual(d.pick(v, cfg, now + 61)[0], "work")
        # uma das contas passa: alerta
        b["rates"][BID] = snap(95, 45)
        v = E.View([("a", a), ("b", b)])
        self.assertEqual(v.limit_account["label"], "B")
        d.pick(v, cfg, now + 200)
        self.assertEqual(d.pick(v, cfg, now + 262)[0], "limit")


# ---------------------------------------------------------------- rótulos editáveis
class Rotulos(unittest.TestCase):
    def test_validate(self):
        out = validate({"account_labels": {AID: "  Pessoal\n", "não-é-id": "x", BID: "\x07", "api": "Chave"}})
        self.assertEqual(out["account_labels"], {AID: "Pessoal", "api": "Chave"})
        self.assertEqual(validate({"account_labels": "x"})["account_labels"], {})
        self.assertEqual(validate({})["account_labels"], {})

    def test_patch_do_painel(self):
        from byorzin_monitor.panel.server import BadRequest, check_settings_patch
        self.assertEqual(check_settings_patch({"account_labels": {AID: " Pessoal ", BID: ""}})["account_labels"],
                         {AID: "Pessoal"})                    # "" = volta ao rótulo padrão
        for bad in ({AID: "a\x00b"}, {AID: "x" * 25}, {"xyz": "ok"}, {AID: 3}, "texto", [AID]):
            with self.assertRaises(BadRequest, msg=bad):
                check_settings_patch({"account_labels": bad})

    def test_rotulo_editado_vale_na_tela(self):
        v = D.demo_view({"account_labels": {D.ACCOUNTS[1][0]: "Casa"}}, accounts=2)
        self.assertIn("Casa", [a["label"] for a in v.accounts])
        with hd_frames.frozen(), recording() as log:
            L.layout_cards(v, 1.0)
            self.assertIn("Casa", [b[0] for b in log])


class Painel(unittest.TestCase):
    def test_estado_do_painel(self):
        from byorzin_monitor.panel import server

        class P(server.Panel):
            def __init__(self, sources, labels=None):
                import threading
                self.fetcher = mock.Mock(lock=threading.Lock(), sources=sources)
                self.fetcher.view = lambda cfg: E.View(list(sources), cfg)
                self._cfg = {"account_labels": labels or {}}

            def current(self):
                return validate(self._cfg)

        a = src("note", None, {"id": AID, "label": "Ana"}, {AID: snap(83, 92)}, [sess("s1", AID)])
        b = src("srv", None, {"id": BID, "label": "Empresa"}, {BID: snap(41, 20)}, [sess("s2", BID)])
        k = src("ci", None, {"id": "api", "label": "API key"}, None, [])
        p = P([("note", a), ("srv", b), ("ci", k)], {AID: "Pessoal"})
        accs = {x["id"]: x for x in p.accounts()}
        self.assertEqual(accs[AID]["label"], "Pessoal")
        self.assertEqual(accs[AID]["default"], "Ana")
        self.assertTrue(accs[AID]["custom"])
        self.assertFalse(accs["api"]["limits"])
        self.assertEqual(accs["api"]["hosts"], ["ci"])
        sm = p.summary()
        self.assertEqual([x["label"] for x in sm["accounts"]], ["Empresa", "Pessoal"])
        self.assertEqual({x["id"]: x["account"] for x in sm["list"]}, {"s1": AID, "s2": BID})
        self.assertEqual(p._machine_account(a), {"id": AID, "label": "Pessoal"})
        self.assertIsNone(p._machine_account(src("velho", snap(1, 1))))
        # uma conta: summary sem lista por conta (painel como sempre)
        p = P([("note", a)])
        self.assertEqual(p.summary()["accounts"], [])
        self.assertEqual(p.summary()["week"], 83)


if __name__ == "__main__":
    unittest.main()
