# Comando `byorzin-monitor`: instala, diagnostica e roda as peças do Byorzin Monitor.
import argparse
import getpass
import grp
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from byorzin_monitor import __version__
from byorzin_monitor.common import (CLAUDE_DIR, CONFIG_DIR, CONFIG_FILE, EVENTS_FILE, LEGACY_CONFIG_DIR,
                                    LEGACY_STATE_DIR, RATE_FILE, STATE_DIR, load_config)

USER_UNITS = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "systemd" / "user"
UNIT_COLLECTOR = "byorzin-monitor-collector.service"
UNIT_PANEL = "byorzin-monitor-panel.service"
UNIT_DISPLAY = "byorzin-monitor-display.service"
UDEV_RULE = "/etc/udev/rules.d/99-byorzin-monitor.rules"
SYSTEM_UNIT = f"/etc/systemd/system/{UNIT_DISPLAY}"
LEGACY_USER_UNITS = ["claude-monitor-collector.service", "claude-monitor-panel.service"]
LEGACY_SYSTEM = ["/etc/systemd/system/claude-monitor-display.service", "/etc/udev/rules.d/99-claude-monitor.rules"]

COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
if COLOR:
    OK, WARN, BAD = "\033[32m✔\033[0m", "\033[33m!\033[0m", "\033[31m✘\033[0m"
else:                     # saída redirecionada (arquivo, pipe, journal): sem códigos ANSI
    OK, WARN, BAD = "✔", "!", "✘"


class UserError(Exception):
    """Erro com mensagem para o usuário: vira 'erro: ...' e código de saída 1, sem traceback."""


def step(msg):
    print(f"\n\033[1;32m==> {msg}\033[0m" if COLOR else f"\n==> {msg}")


def exe_argv():
    """Comando (lista de argumentos) que o systemd e os hooks do Claude devem chamar."""
    cand = Path(sys.executable).parent / "byorzin-monitor"
    if cand.exists():
        return [str(cand)]
    w = shutil.which("byorzin-monitor")
    return [w] if w else [sys.executable, "-m", "byorzin_monitor"]


def exe():
    """Mesmo comando, pronto para o shell (caminhos com espaço vão entre aspas)."""
    return shlex.join(exe_argv())


def systemd_quote(arg):
    """Um argumento para ExecStart= do systemd (aspas duplas; % e $ escapados)."""
    a = str(arg).replace("%", "%%").replace("$", "$$")
    if a and not any(c in a for c in " \t\"'\\;"):
        return a
    return '"' + a.replace("\\", "\\\\").replace('"', '\\"') + '"'


def exec_start(*args):
    return " ".join(systemd_quote(x) for x in exe_argv() + list(args))


def has_systemctl():
    return shutil.which("systemctl") is not None


def run(cmd, check=False, quiet=False):
    try:
        r = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True)
    except FileNotFoundError:       # programa não instalado (ex.: systemctl em máquina sem systemd)
        prog = cmd.split()[0] if isinstance(cmd, str) else cmd[0]
        r = subprocess.CompletedProcess(cmd, 127, "", f"{prog}: comando não encontrado")
    if not quiet and r.returncode != 0 and r.stderr.strip():
        print("   ", r.stderr.strip().splitlines()[-1])
    if check and r.returncode != 0:
        raise UserError(f"falhou: {cmd}")
    return r


def sudo(cmd):
    print(f"   sudo {cmd}")
    return run(f"sudo {cmd}")


def which_sbin(name):
    return shutil.which(name) or next((p for p in (f"/usr/sbin/{name}", f"/sbin/{name}") if os.path.exists(p)), None)


def lan_cidr():
    """Sub-rede da interface padrão (ex.: 10.0.0.0/24), para o firewall. None se não der para saber."""
    import ipaddress
    try:
        out = subprocess.run(["ip", "-o", "-4", "route", "get", "1.1.1.1"], capture_output=True, text=True,
                             timeout=3).stdout.split()
        dev = out[out.index("dev") + 1]
        addrs = subprocess.run(["ip", "-o", "-4", "addr", "show", "dev", dev], capture_output=True, text=True,
                               timeout=3).stdout.split()
        inet = addrs[addrs.index("inet") + 1]
        return str(ipaddress.ip_interface(inet).network)
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        pass
    ip = lan_ip()
    if ip.startswith("127."):
        return None
    return str(ipaddress.ip_network(ip + "/24", strict=False))


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))      # não envia nada; só descobre a interface de saída
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


# ---------------------------------------------------------------- arquivos de sistema
PASS_ENV = ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "CLAUDE_CONFIG_DIR")


def unit_env():
    """Linhas Environment= com as pastas fora do padrão definidas no setup (a unit não herda o shell)."""
    out = ""
    for k in PASS_ENV:
        v = os.environ.get(k)
        if v:
            out += "Environment=" + systemd_quote(f"{k}={v}") + "\n"
    return out


def collector_unit():
    return f"""[Unit]
Description=Byorzin Monitor - coletor (sessões, agentes, tokens, limites)
After=network-online.target

[Service]
{unit_env()}ExecStart={exec_start("collector")}
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""


def panel_unit():
    return f"""[Unit]
Description=Byorzin Monitor - painel web
After=network-online.target

[Service]
{unit_env()}ExecStart={exec_start("panel")}
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""


def display_unit():
    user = getpass.getuser()
    return f"""[Unit]
Description=Byorzin Monitor - tela USB
BindsTo=dev-ttyByorzin.device
After=dev-ttyByorzin.device

[Service]
User={user}
Environment={systemd_quote(f"HOME={Path.home()}")}
{unit_env()}ExecStart={exec_start("display")}
Restart=always
RestartSec=3

[Install]
WantedBy=dev-ttyByorzin.device
"""


def udev_rules():
    from byorzin_monitor.display.backends import KNOWN_USB
    lines = ["# Byorzin Monitor: telas USB conhecidas -> /dev/ttyByorzin e sobe o display ao plugar"]
    for vid, pid, serial, backend, label in KNOWN_USB:
        match = f'SUBSYSTEM=="tty", ATTRS{{idVendor}}=="{vid:04x}", ATTRS{{idProduct}}=="{pid:04x}"'
        if serial:
            match += f', ENV{{ID_SERIAL_SHORT}}=="{serial[1:]}*"' if serial.startswith("^") else \
                f', ENV{{ID_SERIAL_SHORT}}=="*{serial}*"'
        lines.append(f"# {label}")
        lines.append(match + ', SYMLINK+="ttyByorzin", GROUP="dialout", MODE="0660", ENV{ID_MM_DEVICE_IGNORE}="1", '
                     f'TAG+="systemd", ENV{{SYSTEMD_WANTS}}+="{UNIT_DISPLAY}"')
    return "\n".join(lines) + "\n"


def write_root(path, content):
    tmp = STATE_DIR / ("tmp-" + Path(path).name)
    tmp.write_text(content)
    sudo(f"install -m 644 {tmp} {path}")
    tmp.unlink()


# ---------------------------------------------------------------- setup
def migrate_legacy(no_sudo):
    if LEGACY_CONFIG_DIR.exists() and not CONFIG_DIR.exists():
        shutil.copytree(LEGACY_CONFIG_DIR, CONFIG_DIR)
        print(f"   configuração copiada de {LEGACY_CONFIG_DIR}")
    if LEGACY_STATE_DIR.exists() and not STATE_DIR.exists():
        shutil.copytree(LEGACY_STATE_DIR, STATE_DIR, ignore=shutil.ignore_patterns("frame.png", "*.tmp.png"))
        print(f"   dados copiados de {LEGACY_STATE_DIR}")
    for u in LEGACY_USER_UNITS:
        if (USER_UNITS / u).exists() and has_systemctl():
            run(["systemctl", "--user", "disable", "--now", u], quiet=True)
            (USER_UNITS / u).unlink()
            print(f"   serviço antigo removido: {u}")
    legacy = [f for f in LEGACY_SYSTEM if os.path.exists(f)]
    if legacy and no_sudo:
        print(f"   {WARN} restos da versão antiga (claude-monitor) que vão disputar a porta serial da tela:")
        for f in legacy:
            print(f"     {f}")
        print("     remova com: " + "; ".join(
            ([f"sudo systemctl disable --now {Path(f).name}" for f in legacy if f.endswith(".service")]
             + [f"sudo rm -f {' '.join(legacy)}", "sudo systemctl daemon-reload", "sudo udevadm control --reload"])))
    elif legacy:
        for f in legacy:
            if f.endswith(".service"):
                sudo(f"systemctl disable --now {Path(f).name}")
            sudo(f"rm -f {f}")


def cmd_setup(a):
    print(f"Byorzin Monitor {__version__} — instalação nesta máquina ({socket.gethostname()})")
    if sys.platform != "linux":
        raise SystemExit("Por enquanto o setup automático é só para Linux (veja o README).")
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    step("Migrando instalação anterior (se houver)")
    migrate_legacy(a.no_sudo)

    step(f"Configuração ({CONFIG_FILE})")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    from byorzin_monitor.common import config_error
    if not CONFIG_FILE.exists():
        from byorzin_monitor.network import set_config
        set_config(token=a.token or os.urandom(18).hex(), peers=[p.rstrip("/") for p in a.peer])
        print("   criada.")
    else:
        print("   já existe, mantida.")
        if a.peer:
            print("   (para mudar os peers, edite o arquivo)")
    cfg = load_config()
    if config_error():
        raise UserError(f"{CONFIG_FILE}: {config_error()}. Corrija o arquivo e rode o setup de novo.")

    step("Serviços do usuário: coletor e painel")
    USER_UNITS.mkdir(parents=True, exist_ok=True)
    (USER_UNITS / UNIT_COLLECTOR).write_text(collector_unit())
    (USER_UNITS / UNIT_PANEL).write_text(panel_unit())
    if not has_systemctl():
        print(f"   {WARN} systemd (systemctl) não encontrado: as units foram gravadas em {USER_UNITS}, mas")
        print("     nada foi ligado. Rode à mão (ou pelo gerenciador de serviços do seu sistema):")
        print(f"     {exe()} collector   e   {exe()} panel")
    else:
        run(["systemctl", "--user", "daemon-reload"])
        for u in (UNIT_COLLECTOR, UNIT_PANEL):
            run(["systemctl", "--user", "enable", u], quiet=True)
            run(["systemctl", "--user", "restart", u])
            print(f"   {u}: {run(['systemctl', '--user', 'is-active', u], quiet=True).stdout.strip()}")

    if a.no_sudo:
        print("\n(--no-sudo: pulando tela USB, grupo dialout, linger e firewall)")
    elif not has_systemctl():
        print("\n(sem systemd: pulando tela USB automática, linger e firewall; veja docs/telas.md)")
    else:
        step("Partes de sistema (sudo): tela USB, permissões, firewall")
        user = getpass.getuser()
        sudo(f"usermod -aG dialout {user}")
        sudo(f"loginctl enable-linger {user}")
        write_root(UDEV_RULE, udev_rules())
        write_root(SYSTEM_UNIT, display_unit())
        sudo("systemctl daemon-reload")
        sudo(f"systemctl enable {UNIT_DISPLAY}")
        sudo("udevadm control --reload")
        sudo("udevadm trigger --subsystem-match=tty --action=add")
        ufw = which_sbin("ufw")
        if ufw and "Status: active" in run(f"sudo {ufw} status", quiet=True).stdout:
            lan = a.lan or lan_cidr()
            if not lan:
                print(f"   {WARN} não descobri a rede local; firewall não alterado (use --lan 10.0.0.0/24, por exemplo)")
            else:
                print(f"   rede liberada no firewall: {lan}" + ("" if a.lan else " (detectada; mude com --lan)"))
                for port, what in ((cfg["port"], "coletor"), (cfg["panel_port"], "painel")):
                    sudo(f"{ufw} allow from {lan} to any port {port} proto tcp comment 'byorzin-monitor {what}'")
                sudo(f"{ufw} allow from {lan} to any port {cfg.get('discovery_port', 8789)} proto udp comment 'byorzin-monitor descoberta'")

    if not a.no_claude:
        step("Hooks e status line do Claude Code")
        from byorzin_monitor.claude_settings import apply
        apply(exe(), yes=a.yes)

    step("Pronto")
    ip = lan_ip()
    print(f"   Painel: http://{ip}:{cfg['panel_port']}")
    print(f"   Diagnóstico: byorzin-monitor doctor")
    print("\n   Para juntar outra máquina: instale nela (byorzin-monitor setup), gere um código")
    print(f"   aqui (painel → Máquinas, ou: byorzin-monitor pair) e, na outra, rode:")
    print(f"   byorzin-monitor pair {ip} <código>     (ou clique em Parear no painel dela)")
    print("   Alternativa manual: setup --token <token desta máquina> --peer http://" + f"{ip}:{cfg['port']}")
    return 0


# ---------------------------------------------------------------- doctor
def cmd_doctor(a):
    probs = 0

    def check(ok, msg, fix=None, warn=False):
        nonlocal probs
        print(f" {OK if ok else (WARN if warn else BAD)} {msg}")
        if not ok and fix:
            print(f"     → {fix}")
        if not ok and not warn:
            probs += 1

    print(f"Byorzin Monitor {__version__} em {socket.gethostname()}\n")
    check(sys.version_info >= (3, 11), f"Python {sys.version.split()[0]}", "precisa de Python 3.11 ou mais novo")
    for mod in ("serial", "PIL", "numpy", "cairosvg"):
        try:
            __import__(mod)
            check(True, f"biblioteca {mod}")
        except Exception as e:
            check(False, f"biblioteca {mod}: {e}", "sudo apt install libcairo2  (cairosvg) / pipx reinstall byorzin-monitor")
    check(os.path.exists("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"), "fontes DejaVu", "sudo apt install fonts-dejavu-core")

    from byorzin_monitor.common import config_error
    cfg = load_config()
    err = config_error()
    if err:
        check(False, f"{err}", f"corrija {CONFIG_FILE} (enquanto isso, todos usam os padrões no que não deu para ler)")
    else:
        check(CONFIG_FILE.exists() and bool(cfg.get("token")), f"configuração {CONFIG_FILE}", "byorzin-monitor setup")
    svc = {}
    if not has_systemctl():
        check(False, "systemd (systemctl) não encontrado: os serviços não são gerenciados aqui",
              f"rode à mão: {exe()} collector  e  {exe()} panel", warn=True)
    else:
        for u in (UNIT_COLLECTOR, UNIT_PANEL):
            st = run(["systemctl", "--user", "is-active", u], quiet=True).stdout.strip()
            svc[u] = st
            check(st == "active", f"serviço {u}: {st or 'não instalado'}", f"systemctl --user restart {u}  (ou byorzin-monitor setup)")
        linger = "Linger=yes" in run(["loginctl", "show-user", getpass.getuser(), "-p", "Linger"], quiet=True).stdout
        check(linger, "serviços rodam sem login (linger)", f"sudo loginctl enable-linger {getpass.getuser()}", warn=True)

    def get(url):
        req = urllib.request.Request(url + "/state", headers={"Authorization": f"Bearer {cfg.get('token', '')}"})
        with urllib.request.urlopen(req, timeout=2) as r:
            return json.load(r)
    try:
        st = get(f"http://127.0.0.1:{cfg['port']}")
        n = len(st.get("sessions", []))
        check(True, f"coletor responde ({n} {'sessão' if n == 1 else 'sessões'})")
    except Exception as e:
        why = getattr(e, "reason", None) or e
        if svc.get(UNIT_COLLECTOR) == "active":
            check(False, f"o serviço do coletor está ativo, mas nada responde na porta configurada ({cfg['port']}): {why}",
                  f"a porta mudou no config.toml depois que ele subiu? systemctl --user restart {UNIT_COLLECTOR}; "
                  f"veja também journalctl --user -u {UNIT_COLLECTOR} -n 30")
        else:
            check(False, f"coletor não responde na porta {cfg['port']}: {why}", f"journalctl --user -u {UNIT_COLLECTOR} -n 30")
    for p in cfg.get("peers", []):
        try:
            st = get(p.rstrip("/"))
            check(True, f"peer {p} → {st.get('host')}")
        except Exception as e:
            check(False, f"peer {p} não responde: {e}",
                  "a outra máquina está ligada? firewall liberado (porta 8787)? mesmo token?", warn=True)

    # [máquinas] descoberta na rede local
    from byorzin_monitor.network import discover, disc_params, is_paired, machines_meta
    on, dport, _ = disc_params(cfg)
    if not on:
        check(False, "descoberta na rede desligada (discovery = false)", warn=True)
    else:
        found, listening = discover(3.0, cfg)
        own = [m for m in found if m.get("own")]
        check(bool(own), f"descoberta: este coletor se anuncia na porta {dport}/udp",
              "o coletor está rodando? (byorzin-monitor collector)", warn=True)
        if not listening:
            check(False, f"porta {dport}/udp ocupada para ouvir anúncios (o painel já ouve; normal se ele estiver rodando)", warn=True)
        others = [m for m in found if not m.get("own")]
        meta = machines_meta()
        for m in others:
            paired = is_paired(m, cfg, meta)
            check(True, f"na rede: {m['host']} ({m['ip']}) {'— pareada' if paired else '— não pareada: byorzin-monitor pair ' + m['ip'] + ':' + str(m['panel_port']) + ' <código>'}")
        if not others and not cfg.get("peers"):
            check(False, "nenhuma outra máquina na rede (tudo bem se você só usa esta)",
                  f"firewall liberado para {dport}/udp nas outras máquinas?", warn=True)

    from byorzin_monitor.display.backends import detect
    screens = detect()
    if screens:
        for s in screens:
            check(True, f"tela: {s['label']} em {s['device']}")
        in_dialout = "dialout" in {grp.getgrgid(g).gr_name for g in os.getgroups()}
        check(in_dialout, "usuário no grupo dialout (acesso à porta serial)", f"sudo usermod -aG dialout {getpass.getuser()} e faça login de novo")
        check(os.path.exists(UDEV_RULE), "regra udev (liga a tela ao plugar)", "byorzin-monitor setup")
        st = run(["systemctl", "is-active", UNIT_DISPLAY], quiet=True).stdout.strip()
        check(st == "active", f"serviço da tela: {st or 'desconhecido'}", f"journalctl -u {UNIT_DISPLAY} -n 30")
    else:
        check(False, "nenhuma tela USB conhecida conectada (tudo bem se ela está em outra máquina)", warn=True)
    from byorzin_monitor.display.backends import available
    print("   outras saídas disponíveis (ver docs/telas.md):")
    graphical = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    for s in available(f"http://{lan_ip()}:{cfg['panel_port']}"):
        if s["kind"] == "framebuffer" and graphical:
            continue          # com sessão gráfica, o /dev/fbN é do desktop: não sugere
        if s["kind"] != "usb":
            print(f"     · {s['label']}" + (f": {s['device']}" if s["kind"] in ("web", "framebuffer") else ""))
    if graphical:
        print("     (há sessão gráfica: framebuffer não é sugerido; use a página /tela ou o terminal)")

    from byorzin_monitor.claude_settings import installed
    ins = installed()
    check(ins["hooks"] >= 10 and ins["statusline"], f"hooks do Claude Code ({ins['hooks']}) e status line",
          "byorzin-monitor setup  (passo dos hooks)")
    if ins["legacy"]:
        check(False, "hooks da versão antiga (claude-monitor) ainda presentes", "byorzin-monitor setup")
    if EVENTS_FILE.exists():
        age = time.time() - EVENTS_FILE.stat().st_mtime
        check(True, f"último evento do Claude há {int(age // 60)} min")
    else:
        check(False, "nenhum evento recebido ainda", "abra uma sessão nova do Claude Code nesta máquina", warn=True)
    check(RATE_FILE.exists(), "uso da semana/5h conhecido (status line)",
          "aparece após a 1ª resposta de uma sessão com assinatura Pro/Max", warn=True)
    ntp = run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"], quiet=True).stdout.strip()
    check(ntp == "yes", "relógio sincronizado (NTP)", "sudo apt install systemd-timesyncd && sudo timedatectl set-ntp true", warn=True)
    print(f"\n{'Tudo certo!' if not probs else f'{probs} problema(s) encontrado(s).'}  Painel: http://{lan_ip()}:{cfg['panel_port']}")
    return 1 if probs else 0


# ---------------------------------------------------------------- status / uninstall
def cmd_status(a):
    cfg = load_config()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{cfg['panel_port']}/api/state")
        with urllib.request.urlopen(req, timeout=3) as r:
            st = json.load(r)
    except Exception as e:
        print(f"painel não responde ({e}); rode: byorzin-monitor doctor")
        return 1
    s = st["summary"]
    pc = lambda v: "–" if v is None else f"{v:.0f}%"
    print(f"Byorzin Monitor · {st['machine']} · tela {'aqui' if st['screen_here'] else 'em outra máquina'}")
    print("máquinas: " + ", ".join(f"{m['name']} ({'on' if m['up'] else 'off'})" for m in st["machines"]))
    print(f"sessões: {s['active']} {'ativa' if s['active'] == 1 else 'ativas'} de {s['sessions']} · "
          f"esperando você: {s['waiting']} · agentes: {s['agents']}")
    print(f"semana {pc(s['week'])} · 5h {pc(s['five'])} · tokens hoje {s['tok_today']}")
    for x in s["list"]:
        ag = f", {x['agents']} {'agente' if x['agents'] == 1 else 'agentes'}" if x["agents"] else ""
        print(f"  [{x['status']:<8}] {x['label']}  ({x['host']}{ag})")
    return 0


def _panel(cfg, path, body=None):
    req = urllib.request.Request(f"http://127.0.0.1:{cfg['panel_port']}{path}",
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", "X-Byorzin": "1"},
                                 method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=4) as r:
        return json.load(r)


def cmd_pair(a):
    from byorzin_monitor.pairing import PairError, join
    cfg = load_config()
    if not a.target:      # gera um código aqui (pelo painel local, que é quem o valida)
        try:
            r = _panel(cfg, "/api/pair/code", {})
        except Exception as e:
            print(f"painel desta máquina não responde ({e}); ele precisa estar rodando para gerar o código")
            return 1
        print(f"Código: {r['code'][:3]} {r['code'][3:]}   (vale {r['ttl'] // 60} min, uso único)")
        print(f"Na outra máquina: byorzin-monitor pair {lan_ip()}:{cfg['panel_port']} {r['code']}")
        return 0
    if not a.code:
        print("faltou o código: byorzin-monitor pair <ip-ou-url> <código>")
        return 2
    try:
        r = join(a.target, a.code, cfg)
    except PairError as e:
        print(f"{BAD} não pareou: {e.msg}")
        return 1
    print(f"{OK} pareado com {r['host']} ({r['url']})")
    for p in r["peers"]:
        print(f"   + {p} (do grupo de {r['host']})")
    if r["dropped"]:
        print(f"{WARN} saíram do grupo antigo (token diferente): {', '.join(r['dropped'])}")
    print("   Coletor, painel e tela pegam a mudança sozinhos em alguns segundos.")
    return 0


def cmd_machines(a):
    from datetime import datetime
    cfg = load_config()
    try:
        st = _panel(cfg, "/api/machines")
    except Exception:
        st = None
    if st is None:        # sem painel: mostra o config e ouve a rede por 3 s
        from byorzin_monitor.network import discover, is_paired
        print("(painel desta máquina não responde; mostrando config.toml e ouvindo a rede por 3 s)")
        print("Pareadas:")
        for p in cfg.get("peers", []):
            print(f"   {p}")
        found, _ = discover(3.0, cfg)
        found = [m for m in found if not m.get("own") and not is_paired(m, cfg)]
    else:
        print(f"Pareadas (vistas de {st['machine']}):")
        for m in st["paired"]:
            if m["up"]:
                n = m.get("sessions", 0)
                state = f"online · {n} {'sessão' if n == 1 else 'sessões'}"
            elif m.get("seen"):
                state = f"offline · visto em {datetime.fromtimestamp(m['seen']):%d/%m %H:%M}"
            else:
                state = "sem contato"
            print(f"   {'*' if m['local'] else ' '} {m['name']:<16} {state:<34} {m.get('url') or '(esta máquina)'}")
        found = st["found"]
    print("Encontradas na rede (não pareadas):")
    if not found:
        print("   nenhuma")
    for m in found:
        print(f"     {m['host']:<16} {m['ip']}  → byorzin-monitor pair {m['ip']}:{m['panel_port']} <código>")
    return 0


def cmd_panel_url(a):
    """Link do painel para abrir em outro aparelho (celular, outro computador). Quem sabe o link
    completo (com a chave) é o painel local, em GET /api/panel-url, que só responde a 127.0.0.1."""
    cfg = load_config()
    url = f"http://127.0.0.1:{cfg['panel_port']}/api/panel-url"
    try:
        with urllib.request.urlopen(url, timeout=4) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UserError("o painel desta máquina não tem a rota /api/panel-url (versão antiga?). "
                            "Atualize e reinicie o painel: systemctl --user restart " + UNIT_PANEL) from None
        raise UserError(f"o painel respondeu {e.code} em {url}") from None
    except (urllib.error.URLError, OSError) as e:
        raise UserError(f"o painel desta máquina não responde na porta {cfg['panel_port']} "
                        f"({getattr(e, 'reason', e)}). Ele precisa estar rodando: systemctl --user status "
                        f"{UNIT_PANEL}  (ou byorzin-monitor doctor)") from None
    try:
        data = json.loads(body)
        link = data.get("url") or data.get("link") if isinstance(data, dict) else None
    except ValueError:
        link = body.decode(errors="replace").strip() or None
    if not link:
        raise UserError(f"resposta inesperada do painel em {url}")
    print(link)
    if sys.stdout.isatty():
        print("Abra este link no outro aparelho (mesma rede). Ele contém a chave de acesso ao painel: "
              "não compartilhe.", file=sys.stderr)
    return 0


def cmd_uninstall(a):
    from byorzin_monitor.claude_settings import apply
    step("Hooks e status line do Claude Code")
    apply(exe(), remove=True, yes=a.yes)
    step("Serviços do usuário")
    for u in (UNIT_COLLECTOR, UNIT_PANEL):
        run(["systemctl", "--user", "disable", "--now", u], quiet=True)
        (USER_UNITS / u).unlink(missing_ok=True)
    run(["systemctl", "--user", "daemon-reload"])
    if not a.no_sudo:
        step("Partes de sistema (sudo)")
        sudo(f"systemctl disable --now {UNIT_DISPLAY}")
        sudo(f"rm -f {SYSTEM_UNIT} {UDEV_RULE}")
        sudo("systemctl daemon-reload")
        sudo("udevadm control --reload")
    if a.purge:
        shutil.rmtree(CONFIG_DIR, ignore_errors=True)
        shutil.rmtree(STATE_DIR, ignore_errors=True)
        print(f"   apagados {CONFIG_DIR} e {STATE_DIR}")
    else:
        print(f"   mantidos {CONFIG_DIR} e {STATE_DIR} (use --purge para apagar)")
    print("\nPronto. Para remover o programa: pipx uninstall byorzin-monitor")
    return 0


# ---------------------------------------------------------------- main
def build_parser():
    ap = argparse.ArgumentParser(prog="byorzin-monitor", description="Byorzin — monitor compartilhado de agentes do Claude Code")
    ap.add_argument("--version", action="version", version=f"byorzin-monitor {__version__}")
    sub = ap.add_subparsers(dest="cmd", metavar="comando")

    p = sub.add_parser("setup", help="instala/atualiza nesta máquina (serviços, tela, hooks do Claude)")
    p.add_argument("--token", help="token compartilhado (use o da 1ª máquina)")
    p.add_argument("--peer", action="append", default=[], help="endereço de outra máquina, ex.: http://192.168.1.10:8787")
    p.add_argument("--lan", default=None, help="rede liberada no firewall (padrão: a sub-rede da interface principal, ex.: 192.168.1.0/24)")
    p.add_argument("--no-sudo", action="store_true", help="não mexe em nada que precise de sudo")
    p.add_argument("--no-claude", action="store_true", help="não mexe no ~/.claude/settings.json")
    p.add_argument("--yes", "-y", action="store_true", help="não pergunta antes de alterar o settings.json")
    sub.add_parser("doctor", help="diagnóstico com dicas de correção")
    sub.add_parser("status", help="resumo das sessões e máquinas")
    p = sub.add_parser("pair", help="pareia com outra máquina por código (sem argumentos: gera um código aqui)")
    p.add_argument("target", nargs="?", help="IP ou URL do painel da outra máquina, ex.: 192.168.1.10 ou 192.168.1.10:8788")
    p.add_argument("code", nargs="?", help="código de 6 dígitos mostrado na outra máquina")
    sub.add_parser("machines", help="lista máquinas pareadas e as encontradas na rede")
    sub.add_parser("panel-url", help="mostra o link do painel para abrir em outro aparelho (celular, outro PC)")
    p = sub.add_parser("uninstall", help="remove serviços, tela e hooks (devolve a status line anterior)")
    p.add_argument("--purge", action="store_true", help="apaga também configuração e dados")
    p.add_argument("--no-sudo", action="store_true", help="não mexe em nada que precise de sudo")
    p.add_argument("--yes", "-y", action="store_true", help="não pergunta antes de alterar o settings.json")
    for name, help_ in (("collector", "roda o coletor (serviço)"), ("panel", "roda o painel web (serviço)"),
                        ("hook", "chamado pelos hooks do Claude Code"), ("statusline", "status line do Claude Code")):
        sub.add_parser(name, help=help_)
    # "display" tem as próprias opções (display/engine.py); aqui só aparece na lista de comandos
    sub.add_parser("display", help="roda a tela (serviço); veja: byorzin-monitor display --help", add_help=False)
    return ap


def _fail(msg, code=1):
    print(f"byorzin-monitor: erro: {msg}", file=sys.stderr)
    return code


def _dispatch(argv):
    if argv and argv[0] == "display":
        from byorzin_monitor.display.engine import main as m
        return m(argv[1:])
    ap = build_parser()
    a = ap.parse_args(argv)
    if a.cmd == "hook":
        from byorzin_monitor.hooks.hook import main as m
        return m()
    if a.cmd == "statusline":
        from byorzin_monitor.hooks.statusline import main as m
        return m()
    if a.cmd == "collector":
        from byorzin_monitor.collector import main as m
        return m()
    if a.cmd == "panel":
        from byorzin_monitor.panel.server import main as m
        return m()
    fn = {"setup": cmd_setup, "doctor": cmd_doctor, "status": cmd_status, "uninstall": cmd_uninstall,
          "pair": cmd_pair, "machines": cmd_machines, "panel-url": cmd_panel_url}.get(a.cmd)
    if not fn:
        ap.print_help()
        return 0
    return fn(a)


def main(argv=None):
    """Erros esperados viram uma linha 'erro: ...' e código de saída ≠ 0, sem traceback
    (com BYORZIN_DEBUG=1 o traceback aparece)."""
    import errno
    argv = sys.argv[1:] if argv is None else list(argv)
    debug = os.environ.get("BYORZIN_DEBUG") not in (None, "", "0")
    try:
        return _dispatch(argv)
    except KeyboardInterrupt:
        return 130
    except SystemExit:
        raise
    except Exception as e:
        if debug:
            raise
        name = type(e).__name__
        if isinstance(e, (UserError,)) or name in ("DisplayError", "PortInUse"):
            return _fail(str(e))
        if isinstance(e, OSError) and e.errno == errno.EADDRINUSE:
            cfg = load_config()
            what = "painel" if argv[:1] == ["panel"] else "coletor"
            port = cfg["panel_port"] if what == "painel" else cfg["port"]
            return _fail(f"a porta {port} ({what}) já está em uso: outro byorzin-monitor já está rodando "
                         f"(systemctl --user status byorzin-monitor-*) ou outro programa usa a porta. "
                         f"Troque `{'panel_port' if what == 'painel' else 'port'}` no config.toml ou pare o outro.")
        if isinstance(e, PermissionError):
            return _fail(f"sem permissão: {e.filename or e}")
        if isinstance(e, RuntimeError):
            return _fail(str(e))
        return _fail(f"{name}: {e}  (rode com BYORZIN_DEBUG=1 para ver os detalhes)")


if __name__ == "__main__":
    sys.exit(main())
