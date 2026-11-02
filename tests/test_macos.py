# macOS: processo vivo, métricas, pastas, cairo do Homebrew, serviços do launchd, setup/uninstall e
# a espera pela tela. Roda em qualquer sistema: o que é do macOS é simulado (sys.platform, comandos).
import _env  # noqa: F401
import io
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from byorzin_monitor import cli, launchd, sysinfo

ROOT = Path(__file__).resolve().parent.parent

VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               10000.
Pages active:                            200000.
Pages inactive:                           50000.
Pages speculative:                         5000.
Pages throttled:                              0.
Pages wired down:                         80000.
Pages purgeable:                           1000.
"""


def fake_run(outputs):
    """subprocess.run falso: devolve a saída programada para o comando (pelo 1º argumento útil)."""
    def run(cmd, **kw):
        key = cmd[-1] if cmd[0] == "sysctl" else cmd[0]
        return subprocess.CompletedProcess(cmd, 0, outputs[key], "")
    return run


class ProcessoVivo(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(sysinfo, "MACOS", True)
        p.start()
        self.addCleanup(p.stop)

    def test_proprio_processo(self):
        self.assertTrue(sysinfo.pid_alive(os.getpid()))

    def test_procstart_confere_o_inicio(self):
        start = "Mon Nov  2 10:00:00 2026"
        with mock.patch.object(sysinfo, "_lstart", return_value="Mon Nov 2 10:00:00 2026"):
            self.assertTrue(sysinfo.pid_alive(os.getpid(), start))           # espaços não importam
            self.assertFalse(sysinfo.pid_alive(os.getpid(), "Tue Nov 3 09:00:00 2026"))   # PID reaproveitado
        with mock.patch.object(sysinfo, "_lstart", return_value=None):
            self.assertTrue(sysinfo.pid_alive(os.getpid(), start))           # sem ps: fica com o PID

    def test_lstart_usa_ps_em_utc_e_guarda(self):
        calls = []

        def run(cmd, **kw):
            calls.append((cmd, kw["env"].get("TZ"), kw["env"].get("LC_ALL")))
            return subprocess.CompletedProcess(cmd, 0, "Mon Nov  2 10:00:00 2026\n", "")
        sysinfo._LSTART.clear()
        with mock.patch.object(sysinfo.subprocess, "run", run):
            self.assertEqual(sysinfo._lstart(4242), "Mon Nov 2 10:00:00 2026")
            self.assertEqual(sysinfo._lstart(4242), "Mon Nov 2 10:00:00 2026")
        self.assertEqual(calls, [(["ps", "-o", "lstart=", "-p", "4242"], "UTC", "C")])   # 2ª vez veio do cache
        sysinfo._LSTART.clear()

    def test_inexistente_e_invalidos(self):
        self.assertFalse(sysinfo.pid_alive(2 ** 22 + 12345))
        for bad in (None, "", "abc", 0, -1):
            self.assertFalse(sysinfo.pid_alive(bad))

    def test_de_outro_usuario_conta_como_vivo(self):
        with mock.patch.object(sysinfo.os, "kill", side_effect=PermissionError):
            self.assertTrue(sysinfo.pid_alive(1))

    def test_proc_start_e_o_do_ps(self):
        with mock.patch.object(sysinfo, "_lstart", return_value="X") as m:
            self.assertEqual(sysinfo.proc_start(str(os.getpid())), "X")
        m.assert_called_once_with(os.getpid())


@unittest.skipUnless(sys.platform == "linux", "compara com o /proc do Linux")
class ProcessoVivoLinux(unittest.TestCase):
    def test_mesmo_resultado_de_antes(self):
        start = sysinfo.proc_start(os.getpid())
        self.assertTrue(sysinfo.pid_alive(os.getpid(), start))
        self.assertTrue(sysinfo.pid_alive(os.getpid(), None))
        self.assertFalse(sysinfo.pid_alive(os.getpid(), "1"))       # PID reaproveitado
        self.assertFalse(sysinfo.pid_alive(None, None))

    def test_metricas(self):
        idle, total = sysinfo.cpu_times()
        self.assertGreater(total, idle)
        used, tot = sysinfo.memory_gb()
        self.assertGreater(tot, 0)
        self.assertGreater(sysinfo.uptime_s(), 0)


class MetricasMac(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(sysinfo, "MACOS", True)
        p.start()
        self.addCleanup(p.stop)

    def test_memoria(self):
        out = {"hw.memsize": str(16 * 2 ** 30), "vm_stat": VM_STAT}
        with mock.patch.object(sysinfo.subprocess, "run", fake_run(out)):
            used, total = sysinfo.memory_gb()
        avail = (10000 + 50000 + 5000 + 1000) * 16384
        self.assertEqual(total, 16.0)
        self.assertEqual(used, round((16 * 2 ** 30 - avail) / 2 ** 30, 1))

    def test_uptime(self):
        import time
        boot = int(time.time()) - 3600
        out = {"kern.boottime": f"{{ sec = {boot}, usec = 52 }} Mon Nov  2 10:00:00 2026"}
        with mock.patch.object(sysinfo.subprocess, "run", fake_run(out)):
            self.assertAlmostEqual(sysinfo.uptime_s(), 3600, delta=2)

    def test_sem_temperatura(self):
        self.assertIsNone(sysinfo.cpu_temp())

    def test_coletor_usa_as_funcoes_do_sistema(self):
        from byorzin_monitor import collector as C
        hm = C.HostMetrics("http://127.0.0.1:1")
        with mock.patch.object(sysinfo, "cpu_times", side_effect=[(100, 1000), (150, 1100)]), \
                mock.patch.object(sysinfo, "memory_gb", return_value=(5.5, 16.0)), \
                mock.patch.object(sysinfo, "uptime_s", return_value=99), \
                mock.patch.object(C.shutil, "which", lambda *_: None), \
                mock.patch.object(C.urllib.request, "urlopen", side_effect=OSError):
            hm.collect()
            hm.collect()
        self.assertEqual(hm.data["cpu"], 50.0)
        self.assertEqual((hm.data["ram_used_gb"], hm.data["ram_total_gb"], hm.data["uptime_s"]), (5.5, 16.0, 99))
        self.assertIsNone(hm.data["cpu_temp"])


class Cairo(unittest.TestCase):
    def test_homebrew_entra_na_busca(self):
        with mock.patch.object(sysinfo, "MACOS", True), mock.patch.dict(os.environ, {}, clear=False), \
                mock.patch.object(sysinfo.os.path, "isdir", lambda p: p == "/opt/homebrew/lib"):
            os.environ.pop("DYLD_FALLBACK_LIBRARY_PATH", None)
            sysinfo.prepare_cairo()
            v = os.environ["DYLD_FALLBACK_LIBRARY_PATH"].split(":")
            self.assertIn("/opt/homebrew/lib", v)
            self.assertIn("/usr/lib", v)              # os padrões continuam na busca
            sysinfo.prepare_cairo()                   # idempotente
            self.assertEqual(os.environ["DYLD_FALLBACK_LIBRARY_PATH"].split(":"), v)

    def test_linux_nao_mexe(self):
        with mock.patch.object(sysinfo, "MACOS", False), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DYLD_FALLBACK_LIBRARY_PATH", None)
            sysinfo.prepare_cairo()
            self.assertNotIn("DYLD_FALLBACK_LIBRARY_PATH", os.environ)


def _paths(platform, env):
    """CONFIG_DIR/STATE_DIR/hostname como o common.py calcula num processo novo com `platform`."""
    code = ("import sys; sys.platform = %r; import byorzin_monitor.common as c; "
            "print(c.CONFIG_DIR); print(c.STATE_DIR); print(c.DEFAULTS['hostname'])" % platform)
    full = {k: v for k, v in os.environ.items() if not k.startswith("XDG_")}
    full.update(env)
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=full, capture_output=True, text=True, check=True)
    return out.stdout.splitlines()


class Pastas(unittest.TestCase):
    def test_padrao_do_mac(self):
        home = Path.home()
        cfg, st, _ = _paths("darwin", {})
        self.assertEqual(cfg, str(home / "Library/Application Support/byorzin-monitor"))
        self.assertEqual(st, str(home / "Library/Application Support/byorzin-monitor/state"))

    def test_xdg_continua_valendo_no_mac(self):
        cfg, st, _ = _paths("darwin", {"XDG_CONFIG_HOME": "/x/c", "XDG_STATE_HOME": "/x/s"})
        self.assertEqual((cfg, st), ("/x/c/byorzin-monitor", "/x/s/byorzin-monitor"))

    def test_linux_igual_a_antes(self):
        home = Path.home()
        cfg, st, host = _paths("linux", {})
        self.assertEqual((cfg, st), (str(home / ".config/byorzin-monitor"), str(home / ".local/state/byorzin-monitor")))

    def test_hostname_sem_local_so_no_mac(self):
        with mock.patch("socket.gethostname", return_value="MacBook-Pro.local"):
            import socket
            self.assertEqual(socket.gethostname().removesuffix(".local"), "MacBook-Pro")
        code = ("import sys, socket; sys.platform = 'darwin'; socket.gethostname = lambda: 'Mac-de-Ana.local'; "
                "import byorzin_monitor.common as c; print(c.DEFAULTS['hostname'])")
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertEqual(out.stdout.strip(), "Mac-de-Ana")


class HookNaMesmaPasta(unittest.TestCase):
    def _dirs(self, platform, env):
        code = ("import sys; sys.platform = %r; from byorzin_monitor.hooks.hook import state_dir; "
                "import byorzin_monitor.common as c; print(state_dir()); print(c.STATE_DIR)" % platform)
        full = {k: v for k, v in os.environ.items() if not k.startswith("XDG_")}
        full.update(env)
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=full, capture_output=True, text=True, check=True)
        return out.stdout.splitlines()

    def test_hook_e_coletor_usam_a_mesma_pasta(self):
        for platform in ("darwin", "linux"):
            for env in ({}, {"XDG_STATE_HOME": "/x/s"}):
                a, b = self._dirs(platform, env)
                self.assertEqual(a, b, (platform, env))


class Fontes(unittest.TestCase):
    def test_fontes_no_pacote(self):
        from byorzin_monitor.display import scenes as S
        for f in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "LICENSE.txt"):
            self.assertTrue(os.path.isfile(S.BUNDLED_FONT_DIR + f), f)

    def test_sem_fontes_do_sistema_usa_as_do_pacote(self):
        from byorzin_monitor.display import scenes as S
        with mock.patch.object(S.os.path, "exists", lambda p: not str(p).startswith(S.SYSTEM_FONT_DIR)):
            self.assertEqual(S._font_dir(), S.BUNDLED_FONT_DIR)

    def test_desenha_com_as_fontes_do_pacote(self):
        from PIL import ImageFont
        f = ImageFont.truetype(sys.modules["byorzin_monitor.display.scenes"].BUNDLED_FONT_DIR + "DejaVuSans-Bold.ttf", 14)
        self.assertGreater(f.getlength("Byorzin"), 20)


class Launchd(unittest.TestCase):
    def test_plist(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "/x/claude"}):
            data = plistlib.loads(launchd.plist("com.byorzin-monitor.display", ["/a b/byorzin-monitor", "display", "--wait"]))
        self.assertEqual(data["Label"], "com.byorzin-monitor.display")
        self.assertEqual(data["ProgramArguments"], ["/a b/byorzin-monitor", "display", "--wait"])
        self.assertTrue(data["RunAtLoad"] and data["KeepAlive"])
        self.assertEqual(data["EnvironmentVariables"]["CLAUDE_CONFIG_DIR"], "/x/claude")
        self.assertIn("/opt/homebrew/bin", data["EnvironmentVariables"]["PATH"])
        self.assertTrue(data["StandardErrorPath"].endswith("display.log"))

    def test_servicos(self):
        self.assertEqual(launchd.SERVICES["com.byorzin-monitor.display"], ["display", "--wait"])
        self.assertEqual(set(launchd.SERVICES), {f"com.byorzin-monitor.{n}" for n in ("collector", "panel", "display")})

    def _install(self, results):
        calls = []

        def ctl(*args):
            calls.append(args)
            if args[0] == "bootstrap":
                return subprocess.CompletedProcess(args, results.pop(0) if results else 0, "", "Bootstrap failed: 5")
            if args[0] == "print":
                return subprocess.CompletedProcess(args, 0, "\tstate = running\n", "")
            return subprocess.CompletedProcess(args, 0, "", "")
        d = Path(tempfile.mkdtemp(dir=_env.TMP))
        with mock.patch.object(launchd, "AGENTS_DIR", d), mock.patch.object(launchd, "_launchctl", ctl), \
                mock.patch.object(launchd.time, "sleep", lambda *_: None):
            out = launchd.install(["/bin/byorzin-monitor"])
        return out, calls, d

    def test_install_grava_e_sobe(self):
        out, calls, d = self._install([])
        self.assertEqual(set(out.values()), {"running"})
        self.assertEqual(sorted(p.name for p in d.iterdir()),
                         sorted(f"{l}.plist" for l in launchd.SERVICES))
        boot = [c for c in calls if c[0] == "bootstrap"]
        self.assertEqual(len(boot), 3)
        self.assertTrue(all(c[1] == f"gui/{os.getuid()}" for c in boot))
        plistlib.loads((d / "com.byorzin-monitor.collector.plist").read_bytes())

    def test_install_tenta_de_novo(self):
        out, calls, _ = self._install([5, 5, 0])       # 1º serviço: duas recusas e depois sobe
        self.assertEqual(out["com.byorzin-monitor.collector"], "running")

    def test_install_falha_reportada(self):
        out, _, _ = self._install([5] * 6)
        self.assertIn("Bootstrap failed", out["com.byorzin-monitor.collector"])

    def test_estado(self):
        with mock.patch.object(launchd, "_launchctl", return_value=subprocess.CompletedProcess([], 113, "", "")):
            self.assertEqual(launchd.state("x"), "not loaded")

    def test_uninstall(self):
        d = Path(tempfile.mkdtemp(dir=_env.TMP))
        for l in launchd.SERVICES:
            (d / f"{l}.plist").write_text("x")
        calls, printed = [], []

        def ctl(*a):
            calls.append(a)
            if a[0] == "print":          # ainda carregado na 1ª pergunta, descarregado na 2ª
                printed.append(a[1])
                return subprocess.CompletedProcess(a, 0 if printed.count(a[1]) == 1 else 113, "", "")
            return subprocess.CompletedProcess(a, 0, "", "")
        with mock.patch.object(launchd, "AGENTS_DIR", d), mock.patch.object(launchd, "_launchctl", ctl), \
                mock.patch.object(launchd.time, "sleep", lambda *_: None):
            launchd.uninstall()
        self.assertEqual(list(d.iterdir()), [])
        self.assertEqual([c[0] for c in calls], ["bootout", "print", "print"] * 3)   # esperou cada um sair


class Cli(unittest.TestCase):
    def test_dicas_por_sistema(self):
        with mock.patch.object(cli, "MACOS", True):
            self.assertIn("launchctl kickstart -k gui/", cli.restart_hint("panel"))
            self.assertIn("com.byorzin-monitor.panel", cli.restart_hint("panel"))
            self.assertIn("collector.log", cli.log_hint("collector"))
        with mock.patch.object(cli, "MACOS", False):
            self.assertEqual(cli.restart_hint("collector"), "systemctl --user restart byorzin-monitor-collector.service")
            self.assertEqual(cli.restart_hint("display"), "sudo systemctl restart byorzin-monitor-display.service")
            self.assertEqual(cli.log_hint("collector"), "journalctl --user -u byorzin-monitor-collector.service -n 30")
            self.assertEqual(cli.log_hint("display"), "journalctl -u byorzin-monitor-display.service -n 30")

    def _args(self, *extra):
        return cli.build_parser().parse_args(["setup", "--no-claude", *extra])

    def test_setup_no_mac_usa_launchd(self):
        installed = []
        with mock.patch.object(cli, "MACOS", True), mock.patch.object(cli.sys, "platform", "darwin"), \
                mock.patch.object(launchd, "install", lambda argv: installed.append(argv) or {"com.byorzin-monitor.panel": "running"}), \
                mock.patch.object(cli, "sudo", side_effect=AssertionError("sudo no macOS")), \
                mock.patch.object(cli, "setup_linux", side_effect=AssertionError("systemd no macOS")), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.cmd_setup(self._args()), 0)
        self.assertEqual(installed, [cli.exe_argv()])
        self.assertIn("launchd", out.getvalue())

    def test_setup_sem_servicos(self):
        with mock.patch.object(cli, "setup_linux", side_effect=AssertionError), \
                mock.patch.object(cli, "setup_macos", side_effect=AssertionError), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.cmd_setup(self._args("--no-services")), 0)
        self.assertIn("--no-services", out.getvalue())

    def test_setup_recusa_outros_sistemas(self):
        with mock.patch.object(cli.sys, "platform", "win32"), redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                cli.cmd_setup(self._args())

    def test_uninstall_no_mac(self):
        removed = []
        a = cli.build_parser().parse_args(["uninstall", "--yes"])
        with mock.patch.object(cli, "MACOS", True), mock.patch.object(launchd, "uninstall", lambda: removed.append(1)), \
                mock.patch("byorzin_monitor.claude_settings.apply", lambda *a, **k: None), \
                mock.patch.object(cli, "run", side_effect=AssertionError("systemctl no macOS")), \
                mock.patch.object(cli, "sudo", side_effect=AssertionError("sudo no macOS")), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(cli.cmd_uninstall(a), 0)
        self.assertEqual(removed, [1])


class EsperaATela(unittest.TestCase):
    def test_espera_e_acha(self):
        from byorzin_monitor.display import engine
        seq = [[], [], [{"backend": "turing-a", "device": "/dev/cu.usbmodem1", "label": "x"}]]
        with mock.patch("byorzin_monitor.display.backends.detect", lambda: seq.pop(0)), \
                mock.patch.object(engine.time, "sleep", lambda *_: None):
            self.assertTrue(engine.wait_for_screen([]))
        self.assertEqual(seq, [])

    def test_para_quando_pedem(self):
        from byorzin_monitor.display import engine
        stop = []
        with mock.patch("byorzin_monitor.display.backends.detect", lambda: []), \
                mock.patch.object(engine.time, "sleep", lambda *_: stop.append(1)):
            self.assertFalse(engine.wait_for_screen(stop))

    def test_opcao_wait(self):
        from byorzin_monitor.display import engine
        self.assertTrue(engine.build_parser().parse_args(["--wait"]).wait)
        self.assertFalse(engine.build_parser().parse_args([]).wait)


if __name__ == "__main__":
    unittest.main()
