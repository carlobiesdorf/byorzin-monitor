#!/usr/bin/env python3
"""Teste de fumaça de ponta a ponta (CI no Linux e no macOS), com o comando instalado:

setup sem serviços → hook + status line de uma sessão "viva" → coletor e painel rodando →
a sessão aparece no /state do coletor e no painel, a página /tela devolve um JPEG e
`display --png` desenha o quadro (mascote + fontes). Tudo em pastas temporárias e portas livres;
não toca no ~/.config, ~/.claude nem nos serviços de verdade.

uso: python scripts/smoke_test.py [comando]     (padrão: byorzin-monitor do PATH)
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

CMD = sys.argv[1:] or [shutil.which("byorzin-monitor") or "byorzin-monitor"]
SID = "smoke-0000-1111-2222"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def step(msg):
    print(f"==> {msg}", flush=True)


def get(url, token=None, timeout=3):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"} if token else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read()


def wait_for(fn, what, timeout=40):
    t0, last = time.time(), None
    while time.time() - t0 < timeout:
        try:
            r = fn()
            if r:
                return r
        except Exception as e:
            last = e
        time.sleep(0.5)
    raise SystemExit(f"FALHOU: {what} (último erro: {last!r})")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="byorzin-smoke-"))
    # HOME falso e SEM XDG_*: passa pelas pastas padrão de cada sistema (onde hook, status line e
    # coletor precisam concordar), sem tocar no HOME de verdade
    home = tmp / "home"
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("XDG_")}
    env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(tmp / "claude"), NO_COLOR="1")
    if sys.platform == "darwin":
        cfg_dir = home / "Library" / "Application Support" / "byorzin-monitor"
    else:
        cfg_dir = home / ".config" / "byorzin-monitor"
    claude = tmp / "claude"
    (claude / "sessions").mkdir(parents=True)
    (claude / "projects").mkdir()
    (claude / ".claude.json").write_text("{}")
    port, panel_port, disc = free_port(), free_port(), free_port()
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.toml").write_text(
        f'port = {port}\npanel_port = {panel_port}\ndiscovery_port = {disc}\nbind = "127.0.0.1"\n'
        f'token = "smoke"\nhostname = "smoke-host"\n')
    procs = []

    def run(*args, stdin=None, check=True):
        r = subprocess.run(CMD + list(args), input=stdin, env=env, capture_output=True, text=True, timeout=120)
        out = r.stdout + r.stderr
        if "Traceback" in out or (check and r.returncode != 0):
            print(out)
            raise SystemExit(f"FALHOU: byorzin-monitor {' '.join(args)} (saída {r.returncode})")
        return out

    try:
        step(f"{sys.platform}: {' '.join(CMD)} --version")
        print("   ", run("--version").strip())

        step("setup --no-services --no-claude")
        out = run("setup", "--no-services", "--no-claude")
        assert "--no-services" in out, out

        step("sessão viva + eventos de hook + status line")
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        try:
            from byorzin_monitor.sysinfo import proc_start
            start = proc_start(os.getpid())
        except Exception:
            start = None
        (claude / "sessions" / f"{os.getpid()}.json").write_text(json.dumps(
            {"sessionId": SID, "pid": os.getpid(), "procStart": start, "cwd": str(tmp / "meu-projeto"),
             "startedAt": int((time.time() - 300) * 1000)}))
        for ev in ({"hook_event_name": "SessionStart", "source": "startup"},
                   {"hook_event_name": "UserPromptSubmit"},
                   {"hook_event_name": "PreToolUse", "tool_name": "Bash"}):
            run("hook", stdin=json.dumps({"session_id": SID, "cwd": str(tmp / "meu-projeto"), **ev}))
        line = run("statusline", stdin=json.dumps({
            "session_id": SID, "model": {"display_name": "Opus"}, "context_window": {"used_percentage": 42},
            "rate_limits": {"seven_day": {"used_percentage": 30, "resets_at": time.time() + 86400},
                            "five_hour": {"used_percentage": 10, "resets_at": time.time() + 3600}}}))
        assert "Opus" in line and "42%" in line, line
        print("    status line:", line.strip())

        step("coletor e painel")
        for what in ("collector", "panel"):
            log = open(tmp / f"{what}.log", "w")
            procs.append((what, subprocess.Popen(CMD + [what], env=env, stdout=log, stderr=subprocess.STDOUT), log))

        def session_in_state():
            _, _, body = get(f"http://127.0.0.1:{port}/state", "smoke")
            st = json.loads(body)
            s = next((x for x in st.get("sessions", []) if x.get("id") == SID), None)
            return (st, s) if s and s.get("status") == "working" else None
        st, s = wait_for(session_in_state, "a sessão aparecer como 'working' no /state do coletor")
        print(f"    /state: host={st.get('host')} sessão={s.get('project')} status={s.get('status')} "
              f"ferramenta={s.get('tool')}")
        assert st.get("host") == "smoke-host", st.get("host")
        host = st.get("host_metrics") or st.get("host_info") or st.get("metrics") or {}
        print("    métricas da máquina:", {k: host.get(k) for k in ("cpu", "ram_used_gb", "ram_total_gb", "uptime_s")})
        assert (host.get("ram_total_gb") or 0) > 0 and (host.get("uptime_s") or 0) > 0, host
        assert 0 <= (host.get("ram_used_gb") or -1) <= host["ram_total_gb"], host

        def cpu_known():          # a % de CPU sai de duas leituras seguidas
            _, _, body = get(f"http://127.0.0.1:{port}/state", "smoke")
            v = json.loads(body).get("host_metrics", {}).get("cpu")
            return v is not None and 0 <= v <= 100
        wait_for(cpu_known, "a % de CPU aparecer", timeout=60)
        evs = list(cfg_dir.rglob("events.jsonl")) + list((home / ".local").rglob("events.jsonl"))
        assert len(evs) == 1, f"eventos do hook em lugares diferentes: {evs}"

        def panel_sees():
            _, _, body = get(f"http://127.0.0.1:{panel_port}/api/state")
            return json.loads(body) if SID in body.decode() else None
        wait_for(panel_sees, "o painel mostrar a sessão")
        print("    painel: ok")

        code, ctype, jpg = wait_for(lambda: get(f"http://127.0.0.1:{panel_port}/tela/frame.jpg", timeout=20),
                                    "a página /tela devolver um quadro")
        assert code == 200 and ctype.startswith("image/jpeg") and jpg[:2] == b"\xff\xd8", (code, ctype)
        print(f"    /tela/frame.jpg: {len(jpg)} bytes")

        step("display --png (mascote e fontes)")
        png = tmp / "quadro.png"
        run("display", "--png", str(png))
        from PIL import Image
        im = Image.open(png)
        assert im.size == (480, 320), im.size
        assert len(im.convert("RGB").resize((48, 32)).getcolors(48 * 32)) > 20, "quadro quase vazio"
        print(f"    {png.name}: {im.size[0]}x{im.size[1]}")
        if os.environ.get("SMOKE_ARTIFACT"):
            shutil.copy(png, os.environ["SMOKE_ARTIFACT"])

        step("doctor (sem traceback)")
        out = run("doctor", check=False)
        print("   ", "\n    ".join(out.strip().splitlines()[-4:]))

        print("\nOK: teste de fumaça passou")
        return 0
    finally:
        for what, p, log in procs:
            p.terminate()
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
            log.close()
        if os.environ.get("SMOKE_VERBOSE") or sys.exc_info()[0]:
            for what, _, _ in procs:
                print(f"--- {what}.log ---\n" + (tmp / f"{what}.log").read_text()[-3000:])
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
