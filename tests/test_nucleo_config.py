# Núcleo: config.toml inválido, set_config, status line no uninstall, erros da CLI, instalação.
import _env  # noqa: F401
import contextlib
import io
import json
import os
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from byorzin_monitor import cli, common
from byorzin_monitor import claude_settings as CS
from byorzin_monitor import network as net
from byorzin_monitor.common import CONFIG_FILE, load_config

ROOT = Path(__file__).resolve().parent.parent
ORIG = CONFIG_FILE.read_text() if CONFIG_FILE.exists() else ""


class ConfigCase(unittest.TestCase):
    def setUp(self):
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.saved = CONFIG_FILE.read_text() if CONFIG_FILE.exists() else None

    def tearDown(self):
        if self.saved is None:
            CONFIG_FILE.unlink(missing_ok=True)
        else:
            CONFIG_FILE.write_text(self.saved)


class InvalidConfigTest(ConfigCase):
    def test_nao_derruba_e_aproveita_o_resto(self):
        CONFIG_FILE.write_text('token = "abc"\nport = 1234\npeers = [\n  "http://a:1"\n  "http://b:1",\n]\nhostname = "maq"\n')
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            cfg = load_config()
            load_config()                                  # avisa uma vez só
        self.assertEqual(err.getvalue().count("inválido"), 1)
        self.assertEqual((cfg["token"], cfg["port"], cfg["hostname"]), ("abc", 1234, "maq"))
        self.assertIn("panel_port", cfg)                   # padrões continuam lá
        self.assertIn("linha", common.config_error())
        with self.assertRaises(tomllib.TOMLDecodeError):
            load_config(strict=True)

    def test_erro_na_ultima_linha(self):
        CONFIG_FILE.write_text('port = 27999\ntoken = "tk"\nport = \n')
        with contextlib.redirect_stderr(io.StringIO()):
            cfg = load_config()
        self.assertEqual((cfg["port"], cfg["token"]), (27999, "tk"))

    def test_statusline_com_config_invalido(self):
        CONFIG_FILE.write_text("isto não é toml = = =\n")
        env = {**os.environ, "PYTHONPATH": str(ROOT), "XDG_STATE_HOME": tempfile.mkdtemp(dir=_env.TMP)}
        r = subprocess.run([sys.executable, "-m", "byorzin_monitor", "statusline"], input='{"model":{"display_name":"Opus"}}',
                           capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual(r.returncode, 0)
        self.assertIn("Opus", r.stdout)
        self.assertNotIn("Traceback", r.stderr)

    def test_doctor_aponta_a_linha(self):
        CONFIG_FILE.write_text('token = "abc"\nport = \n')
        with contextlib.redirect_stderr(io.StringIO()):
            err = common.config_error()
        self.assertRegex(err, r"config.toml inválido na linha 2")

    def test_live_config_mantem_o_anterior(self):
        CONFIG_FILE.write_text('token = "bom"\n')
        live = net.LiveConfig(every=0)
        time.sleep(0.01)
        CONFIG_FILE.write_text('token = "pela metade\n')
        os.utime(CONFIG_FILE, ns=(time.time_ns() + 10**9, time.time_ns() + 10**9))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(live.token(), "bom")


class SetConfigTest(ConfigCase):
    def test_multilinha_escapes_e_secoes(self):
        CONFIG_FILE.write_text('# topo\ntoken = "t"\npeers = [\n  "http://a:8787",\n  "http://b:8787",\n]\n'
                               'chave_x = 3\n\n[extra]\npeers = "não mexer"\nn = 1.5\n\n[extra.sub]\nk = true\n'
                               '\n[[lista]]\na = 1\n[[lista]]\na = 2\n')
        net.set_config(peers=["http://c:8787"], hostname='a"b\\c\x7f\x01\n', statusline_chain="echo 'oi' \"x\"")
        txt = CONFIG_FILE.read_text()
        self.assertTrue(txt.startswith("# topo\n"))
        cfg = tomllib.loads(txt)
        self.assertEqual(cfg["peers"], ["http://c:8787"])
        self.assertEqual(cfg["hostname"], 'a"b\\c\x7f\x01\n')
        self.assertEqual(cfg["statusline_chain"], "echo 'oi' \"x\"")
        self.assertEqual(cfg["chave_x"], 3)
        self.assertEqual(cfg["extra"], {"peers": "não mexer", "n": 1.5, "sub": {"k": True}})
        self.assertEqual(cfg["lista"], [{"a": 1}, {"a": 2}])
        net.set_config(statusline_chain=None)
        self.assertFalse(load_config(strict=True).get("statusline_chain"))
        self.assertNotIn("statusline_chain", CONFIG_FILE.read_text())

    def test_nao_grava_por_cima_de_arquivo_invalido(self):
        CONFIG_FILE.write_text("token = \n")
        with self.assertRaises(ValueError):
            net.set_config(token="x")
        self.assertEqual(CONFIG_FILE.read_text(), "token = \n")


class UninstallStatuslineTest(ConfigCase):
    def setUp(self):
        super().setUp()
        self.settings_saved = CS.SETTINGS.read_text() if CS.SETTINGS.exists() else None
        CONFIG_FILE.write_text('token = "t"\n\n[secao]\nx = 1\n')

    def tearDown(self):
        if self.settings_saved is None:
            CS.SETTINGS.unlink(missing_ok=True)
        else:
            CS.SETTINGS.write_text(self.settings_saved)
        for b in CS.SETTINGS.parent.glob("settings.json.bak-byorzin-*"):
            b.unlink()
        super().tearDown()

    def test_instala_e_remove_devolvendo_a_status_line(self):
        self.assertTrue(str(CS.SETTINGS).startswith(str(_env.TMP)))     # nunca o ~/.claude de verdade
        CS.SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        orig = {"statusLine": {"type": "command", "command": "~/minha-linha.sh --cor"}, "model": "opus"}
        CS.SETTINGS.write_text(json.dumps(orig))
        CS.apply("/opt/x y/byorzin-monitor", yes=True, out=lambda *a: None)
        s = json.loads(CS.SETTINGS.read_text())
        self.assertTrue(s["statusLine"]["command"].endswith(" statusline"))
        cfg = load_config(strict=True)
        self.assertEqual(cfg["statusline_chain"], "~/minha-linha.sh --cor")
        self.assertEqual(cfg["secao"], {"x": 1})                      # não caiu dentro de [secao]
        CS.apply("/opt/x y/byorzin-monitor", remove=True, yes=True, out=lambda *a: None)
        s = json.loads(CS.SETTINGS.read_text())
        self.assertEqual(s, orig)
        self.assertFalse(load_config(strict=True).get("statusline_chain"))
        self.assertNotIn("statusline_chain", CONFIG_FILE.read_text())


class _PanelUrl(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/api/panel-url":
            body = json.dumps({"url": "http://192.168.1.9:8788/#k=abc"}).encode()
            self.send_response(200)
        else:
            body = b"{}"
            self.send_response(404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_cli(*args, env=None):
    e = {**os.environ, "PYTHONPATH": str(ROOT), "XDG_STATE_HOME": tempfile.mkdtemp(dir=_env.TMP), **(env or {})}
    return subprocess.run([sys.executable, "-m", "byorzin_monitor", *args], capture_output=True, text=True, env=e, timeout=30)


class CliErrorsTest(ConfigCase):
    def test_argumento_desconhecido(self):
        r = run_cli("display", "--pgn", "x.png")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--pgn", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_display_help_lista_backends(self):
        r = run_cli("display", "--help")
        self.assertEqual(r.returncode, 0)
        for b in ("turing-a", "terminal", "framebuffer", "web", "--size", "--bpp", "grade"):
            self.assertIn(b, r.stdout)

    def test_backend_desconhecido_e_tela_ausente(self):
        r = run_cli("display", "--backend", "nada")
        self.assertEqual(r.returncode, 1)
        self.assertIn("tela desconhecida", r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        r = run_cli("display", "--backend", "turing-a", "--device", "/dev/nao-existe-byorzin")
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)
        r = run_cli("display", "--backend", "framebuffer", "--device", str(_env.TMP / "nada.raw"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("--size", r.stderr)

    def test_auto_sem_tela(self):
        with mock.patch("byorzin_monitor.display.backends.detect", lambda: []):
            from byorzin_monitor.display.backends import open_backend
            with self.assertRaises(RuntimeError) as cm:
                open_backend("auto")
        self.assertIn("--backend terminal", str(cm.exception))

    def test_porta_ocupada(self):
        from byorzin_monitor.collector import PortInUse, bind_server
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        try:
            with self.assertRaises(PortInUse) as cm:
                bind_server("127.0.0.1", port, BaseHTTPRequestHandler, "coletor")
            self.assertIn(str(port), str(cm.exception))
            CONFIG_FILE.write_text(f'port = {port}\npanel_port = {port}\nbind = "127.0.0.1"\ntoken = "t"\n')
            r = run_cli("collector")
            self.assertEqual(r.returncode, 1)
            self.assertIn("já está em uso", r.stderr)
            self.assertNotIn("Traceback", r.stderr)
        finally:
            s.close()

    def test_framebuffer_em_arquivo_pela_cli(self):
        raw = _env.TMP / "fb-teste.raw"
        port = _free_port()
        CONFIG_FILE.write_text(f'port = {port}\npanel_port = {_free_port()}\nbind = "127.0.0.1"\ntoken = "t"\n')
        from byorzin_monitor.display import engine
        real_sleep = time.sleep

        def sleep(sec):          # para o laço da tela no 1º quadro; as outras threads dormem normal
            if threading.current_thread() is threading.main_thread():
                raise KeyboardInterrupt
            real_sleep(sec)
        with mock.patch.object(engine.time, "sleep", sleep), \
                mock.patch.object(engine.Renderer, "wait_ready", lambda self, timeout=2.5: False), \
                mock.patch.object(engine, "save_frame", lambda img: None):
            rc = engine.main(["--backend", "framebuffer", "--device", str(raw), "--size", "480x320", "--bpp", "16"])
        self.assertEqual(rc, 0)
        self.assertEqual(raw.stat().st_size, 480 * 320 * 2)
        self.assertTrue(any(raw.read_bytes()))          # desenhou algo

    def test_panel_url(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _PanelUrl)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            CONFIG_FILE.write_text(f'panel_port = {srv.server_address[1]}\n')
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(cli.main(["panel-url"]), 0)
            self.assertEqual(out.getvalue().strip(), "http://192.168.1.9:8788/#k=abc")
        finally:
            srv.shutdown()
            srv.server_close()
        CONFIG_FILE.write_text(f'panel_port = {_free_port()}\n')
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(cli.main(["panel-url"]), 1)
        self.assertIn("não responde", err.getvalue())


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class InstallTest(unittest.TestCase):
    def test_espacos_no_caminho_e_ambiente_nas_units(self):
        with mock.patch.object(cli, "exe_argv", lambda: ["/opt/meu app/bin/byorzin-monitor"]), \
                mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "/tmp/c f g", "CLAUDE_CONFIG_DIR": "/tmp/cl"}):
            self.assertEqual(cli.exe(), "'/opt/meu app/bin/byorzin-monitor'")
            u = cli.display_unit()
            self.assertIn('ExecStart="/opt/meu app/bin/byorzin-monitor" display', u)
            self.assertIn('Environment="XDG_CONFIG_HOME=/tmp/c f g"', u)
            self.assertIn("Environment=CLAUDE_CONFIG_DIR=/tmp/cl", u)
            self.assertIn('ExecStart="/opt/meu app/bin/byorzin-monitor" collector', cli.collector_unit())
            cfg, _ = CS.add({}, cli.exe())
            self.assertEqual(cfg["hooks"]["Stop"][0]["hooks"][0]["command"], "'/opt/meu app/bin/byorzin-monitor' hook")
            self.assertTrue(CS._ours_hook(cfg["hooks"]["Stop"][0]["hooks"][0]["command"]))

    def test_rede_detectada(self):
        def fake_run(args, **kw):
            out = {"route": "1.1.1.1 via 10.20.0.1 dev enp3s0 src 10.20.30.40 uid 1000\n",
                   "addr": "2: enp3s0    inet 10.20.30.40/22 brd 10.20.31.255 scope global enp3s0\n"}
            return subprocess.CompletedProcess(args, 0, out["route" if "route" in args else "addr"], "")
        with mock.patch.object(cli.subprocess, "run", fake_run):
            self.assertEqual(cli.lan_cidr(), "10.20.28.0/22")

    def test_sem_systemctl(self):
        r = cli.run(["comando-que-nao-existe-byorzin", "x"], quiet=True)
        self.assertEqual(r.returncode, 127)

    def test_doctor_sem_tty_sem_ansi(self):
        env = {**os.environ, "PYTHONPATH": str(ROOT)}
        r = subprocess.run([sys.executable, "-c", "import byorzin_monitor.cli as c; print(c.OK, c.BAD); c.step('x')"],
                           capture_output=True, text=True, env=env, timeout=20)
        self.assertNotIn("\033[", r.stdout)


class HookLatencyTest(unittest.TestCase):
    def test_hook_rapido(self):
        env = {**os.environ, "PYTHONPATH": str(ROOT), "XDG_STATE_HOME": tempfile.mkdtemp(dir=_env.TMP)}
        inp = b'{"session_id":"lat","hook_event_name":"PreToolUse","tool_name":"Bash","cwd":"/tmp/x"}'

        def med(code, n=9):
            ts = []
            for _ in range(n):
                t = time.perf_counter()
                subprocess.run([sys.executable, "-c", code], input=inp, env=env, check=True)
                ts.append(time.perf_counter() - t)
            return statistics.median(ts) * 1000
        bare = med("pass")
        hook = med("import sys; from byorzin_monitor.entry import main; sys.exit(main(['hook']))")
        print(f"\n  latência do hook: {hook:.0f} ms (python vazio: {bare:.0f} ms)", file=sys.stderr)
        # o hook em si custa pouco além do interpretador (máquinas de CI do macOS são mais lentas)
        self.assertLess(hook - bare, 60 if sys.platform == "darwin" else 30)
        if bare < 50:
            self.assertLess(hook, 80)
        # e não carrega o resto do pacote
        r = subprocess.run([sys.executable, "-c", "import sys; from byorzin_monitor.entry import main; main(['hook']); "
                            "print(sorted(m for m in sys.modules if m.startswith(('byorzin_monitor', 'argparse', 'urllib.request'))))"],
                           input=inp, env=env, capture_output=True, check=True)
        mods = eval(r.stdout.decode().strip().splitlines()[-1])
        self.assertEqual(mods, ["byorzin_monitor", "byorzin_monitor.entry", "byorzin_monitor.hooks", "byorzin_monitor.hooks.hook"])


if __name__ == "__main__":
    unittest.main()
