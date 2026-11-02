# sysinfo: o que depende do sistema operacional (Linux ou macOS) para o coletor e a tela —
# processo vivo, CPU, memória, uptime, temperatura e a lib cairo do Homebrew. No Linux é o mesmo
# código de antes (lido de /proc e /sys); o resto do programa só chama as funções daqui.
import os
import re
import subprocess
import sys
from pathlib import Path

MACOS = sys.platform == "darwin"


def pid_alive(pid, proc_start=None):
    """O processo `pid` ainda existe? No Linux, `proc_start` (início do processo, do arquivo de sessão
    do Claude Code) evita confundir com outro programa que reaproveitou o mesmo número."""
    if MACOS:
        return _pid_alive_macos(pid, proc_start)
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    if proc_start:
        start = stat.rsplit(")", 1)[1].split()[19]
        return start == str(proc_start)
    return True


_LSTART = {}     # pid -> (quando leu, início do processo): o coletor pergunta a cada poucos segundos


def _lstart(pid):
    """Início do processo como o Claude Code grava em `procStart` fora do Linux:
    a saída de `LC_ALL=C TZ=UTC ps -o lstart= -p <pid>`. None se não deu para ler."""
    import time
    now = time.time()
    hit = _LSTART.get(pid)
    if hit and now - hit[0] < 30:
        return hit[1]
    try:
        out = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=3,
                             env=dict(os.environ, LC_ALL="C", TZ="UTC")).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    v = " ".join(out.split()) or None
    if len(_LSTART) > 512:
        _LSTART.clear()
    _LSTART[pid] = (now, v)
    return v


def _pid_alive_macos(pid, proc_start=None):
    # sem /proc: pergunta ao kernel com o sinal 0 (não mata nada); com `procStart`, confere o
    # início do processo para não confundir com outro que reaproveitou o número
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:     # existe, mas é de outro usuário
        return True
    except OSError:
        return False
    if proc_start:
        cur = _lstart(pid)
        if cur is not None:                 # sem `ps` legível, fica só com o PID
            return cur == " ".join(str(proc_start).split())
    return True


def proc_start(pid):
    """Início do processo no formato que o Claude Code grava em `procStart`."""
    if MACOS:
        return _lstart(int(pid))
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


# ---------------------------------------------------------------- CPU, memória, uptime
def cpu_times():
    """(ocioso, total) em tiques desde o boot; a % de uso sai da diferença entre duas leituras."""
    if MACOS:
        return _cpu_times_macos()
    v = list(map(int, Path("/proc/stat").read_text().split("\n", 1)[0].split()[1:]))
    return v[3] + v[4], sum(v)


_MACH = None     # (libSystem, porta do host): mach_host_self() cria um direito novo a cada chamada


def _cpu_times_macos():
    import ctypes
    global _MACH
    if _MACH is None:
        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        libc.mach_host_self.restype = ctypes.c_uint
        _MACH = (libc, libc.mach_host_self())
    libc, host = _MACH
    info = (ctypes.c_uint * 4)()                 # user, system, idle, nice (CPU_STATE_MAX = 4)
    count = ctypes.c_uint(4)
    HOST_CPU_LOAD_INFO = 3
    if libc.host_statistics(host, HOST_CPU_LOAD_INFO, ctypes.byref(info), ctypes.byref(count)) != 0:
        raise OSError("host_statistics falhou")
    return info[2], sum(info)


def memory_gb():
    """(usada, total) em GB, como o Linux conta: total menos o disponível."""
    if MACOS:
        return _memory_gb_macos()
    mi = {l.split(":")[0]: int(l.split()[1]) for l in Path("/proc/meminfo").read_text().splitlines() if l.split()[1:]}
    return round((mi["MemTotal"] - mi["MemAvailable"]) / 1048576, 1), round(mi["MemTotal"] / 1048576, 1)


def _sysctl(name):
    return subprocess.run(["sysctl", "-n", name], capture_output=True, text=True, timeout=3).stdout.strip()


def _memory_gb_macos():
    total = int(_sysctl("hw.memsize"))
    out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=3).stdout
    page = int(re.search(r"page size of (\d+)", out).group(1))
    pages = {k.strip(): int(v.strip().rstrip(".")) for k, v in re.findall(r"^([^:\n]+):\s+(\d+)\.?$", out, re.M)}
    # "disponível" à moda do Linux: livre + inativa + especulativa + o que pode ser descartado
    avail = sum(pages.get(k, 0) for k in ("Pages free", "Pages inactive", "Pages speculative", "Pages purgeable"))
    used = max(0, total - avail * page)
    return round(used / 2 ** 30, 1), round(total / 2 ** 30, 1)


def uptime_s():
    if MACOS:
        import time
        m = re.search(r"sec = (\d+)", _sysctl("kern.boottime"))
        if not m:
            raise OSError("kern.boottime ilegível")
        return int(time.time() - int(m.group(1)))
    return int(float(Path("/proc/uptime").read_text().split()[0]))


def cpu_temp():
    """Temperatura da CPU em °C, ou None (no macOS só com root; não mostramos)."""
    if MACOS:
        return None
    for hw in Path("/sys/class/hwmon").glob("hwmon*"):
        try:
            if (hw / "name").read_text().strip() in ("k10temp", "coretemp", "zenpower", "cpu_thermal"):
                return int((hw / "temp1_input").read_text()) / 1000
        except OSError:
            continue
    return None


# ---------------------------------------------------------------- cairo (macOS)
HOMEBREW_LIBS = ("/opt/homebrew/lib", "/usr/local/lib")     # Apple Silicon, Intel


def prepare_cairo():
    """No macOS, o cairo do Homebrew fica fora da busca padrão de bibliotecas no Apple Silicon.
    O cairocffi procura com ctypes.util.find_library, que lê DYLD_FALLBACK_LIBRARY_PATH na hora:
    basta acrescentar as pastas do Homebrew antes de importar o cairosvg. No Linux não faz nada."""
    if not MACOS:
        return
    # sem a variável, a busca usa ~/lib, /usr/local/lib e /usr/lib; com ela, só o que estiver nela
    cur = [p for p in os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "").split(":") if p] or \
        [str(Path.home() / "lib"), "/usr/local/lib", "/usr/lib"]
    add = [p for p in HOMEBREW_LIBS if p not in cur and os.path.isdir(p)]
    if add:
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join(cur + add)
