# launchd: serviços do Byorzin Monitor no macOS (o equivalente às units do systemd no Linux).
# Três agentes do usuário em ~/Library/LaunchAgents: coletor, painel e tela. A tela não depende de
# udev: o agente fica rodando `display --wait`, que espera a tela USB ser plugada.
import os
import plistlib
import subprocess
import time
from pathlib import Path

from byorzin_monitor.common import STATE_DIR

AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
PREFIX = "com.byorzin-monitor"
SERVICES = {        # rótulo -> argumentos do byorzin-monitor
    f"{PREFIX}.collector": ["collector"],
    f"{PREFIX}.panel": ["panel"],
    f"{PREFIX}.display": ["display", "--wait"],
}
PASS_ENV = ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "CLAUDE_CONFIG_DIR")
# o launchd começa com um PATH mínimo; nvidia-smi/docker/ollama do Homebrew ficam aqui
PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def plist_path(label):
    return AGENTS_DIR / f"{label}.plist"


def plist(label, argv):
    """Conteúdo (bytes) do .plist de um agente: sobe no login, reinicia se cair."""
    env = {"PATH": PATH}
    for k in PASS_ENV:
        if os.environ.get(k):
            env[k] = os.environ[k]
    name = label.rsplit(".", 1)[1]
    log = str(STATE_DIR / f"{name}.log")
    return plistlib.dumps({
        "Label": label,
        "ProgramArguments": [str(x) for x in argv],
        "EnvironmentVariables": env,
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,          # se sair, volta em 10 s (cabo da tela desplugado, por exemplo)
        "ProcessType": "Interactive" if name == "display" else "Standard",   # Background = CPU/IO limitados
        "StandardOutPath": log,
        "StandardErrorPath": log,
    })


def _domain():
    return f"gui/{os.getuid()}"


def _launchctl(*args):
    try:
        return subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as e:
        return subprocess.CompletedProcess(args, 127, "", str(e))


def install(exe_argv):
    """Grava os agentes e (re)inicia cada um. Devolve {rótulo: "running" | mensagem de erro}."""
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    out = {}
    for label, args in SERVICES.items():
        path = plist_path(label)
        if _launchctl("bootout", f"{_domain()}/{label}").returncode == 0:   # versão anterior rodando
            for _ in range(30):              # espera o launchd soltar o rótulo (até ~15 s)
                if _launchctl("print", f"{_domain()}/{label}").returncode != 0:
                    break
                time.sleep(0.5)
        path.write_bytes(plist(label, list(exe_argv) + args))
        for attempt in range(6):     # mesmo assim ele às vezes recusa por um instante (erro 5 ou 37)
            r = _launchctl("bootstrap", _domain(), str(path))
            if r.returncode == 0:
                break
            time.sleep(1)
        if r.returncode != 0:
            msg = (r.stderr or r.stdout).strip() or f"launchctl saiu com {r.returncode}"
            if r.returncode == 125 or "domain" in msg.lower():
                msg += (" — sem sessão gráfica (setup por SSH?). Entre no Mac pela tela uma vez e rode o "
                        "setup de novo; os serviços ficam instalados em " + str(AGENTS_DIR))
            out[label] = msg
            continue
        out[label] = state(label)
    return out


def state(label):
    """"running", "waiting" (carregado, sem processo) ou "not loaded"."""
    r = _launchctl("print", f"{_domain()}/{label}")
    if r.returncode != 0:
        return "not loaded"
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith("state = "):
            return line.split("=", 1)[1].strip()
    return "loaded"


def restart(label):
    return _launchctl("kickstart", "-k", f"{_domain()}/{label}").returncode == 0


def uninstall():
    for label in SERVICES:
        _launchctl("bootout", f"{_domain()}/{label}")
        plist_path(label).unlink(missing_ok=True)
