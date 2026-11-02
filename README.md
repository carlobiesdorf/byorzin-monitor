<p align="center">
  <img src="docs/img/icon.png" alt="Byorzin, the robot mascot" width="96">
</p>

<h1 align="center">Byorzin Monitor</h1>

<p align="center">
  <strong>Every Claude Code session and subagent, from all your computers, on one screen.</strong><br>
  Many computers, many Claude accounts, one screen: a USB display, or any browser.
</p>

<p align="center">
  <a href="https://github.com/carlobiesdorf/byorzin-monitor/actions/workflows/ci.yml"><img src="https://github.com/carlobiesdorf/byorzin-monitor/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-39ff88" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-3776ab" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/platform-Linux-555" alt="Platform: Linux">
</p>

<p align="center">
  <b>English</b> · <a href="README.pt-BR.md">Português (Brasil)</a>
</p>

<p align="center">
  <img src="docs/img/hero.png" alt="Byorzin Monitor: a 3.5-inch USB screen showing four Claude Code sessions as little robots, next to the web panel" width="900">
</p>

Each computer where you use Claude Code runs a tiny **collector**. One **screen** shows the
sessions and subagents of all of them, each as a **Byorzin**, a small robot that works, calls
subagents, raises its hand when it is **waiting for you**, celebrates when a long task finishes and
sleeps (and dreams about your stats) when nobody is around.

> **No USB screen? No problem.** Open `http://localhost:8788/tela` in any browser: the same layouts,
> drawn in high resolution, on a monitor, TV, tablet or phone.

## Why

- **Many computers, many Claude accounts, one screen.** Workstation, laptop and server (each on
  its own Claude account if you like) appear together. Pair machines with a 6-digit code.
- **Understand it at a glance.** Working, thinking, waiting for you, error, limit reached, asleep:
  you can tell which session needs you from across the room.
- **Any screen.** A cheap 3.5" USB display, any browser (`/tela`), a terminal pane or a Linux
  framebuffer.
- **Privacy first.** Only metadata (event names, tool names, agent types, token counts). Never
  prompts, commands, file contents or answers. Nothing leaves your network.
- **Plug and play.** One `setup` command; plug the USB screen in and it starts drawing.

## Quick start

Requirements: Linux, Python 3.11+, Claude Code, and Cairo + DejaVu fonts
(`sudo apt install libcairo2 fonts-dejavu-core` on Debian/Ubuntu).

**1. Install**

```bash
pipx install git+https://github.com/carlobiesdorf/byorzin-monitor
```

or from a clone (creates `.venv` and runs `setup` for you, so skip step 2):

```bash
git clone https://github.com/carlobiesdorf/byorzin-monitor && cd byorzin-monitor && ./install.sh
```

**2. Set up this computer**

```bash
byorzin-monitor setup
```

It starts the collector (port 8787) and the panel (port 8788) as systemd user services and adds
the Claude Code hooks (it shows the change to `~/.claude/settings.json` and asks first). It asks
for sudo once for the system part (USB screen permissions, udev rule, firewall): with a supported
screen, the screen then turns on by itself whenever you plug it in. Without a screen, the same
setup leaves the panel and `/tela` ready. Use `--no-sudo` to skip the sudo steps.

**3. Open the panel**

Go to **http://localhost:8788** on this computer, or **http://localhost:8788/tela** for the
screen in a browser. For a phone or another PC, get a link with `byorzin-monitor panel-url`
(or panel → **Machines** → *Access from another device*). Sessions that were already open start
reporting once Claude Code reloads its settings.

Something not working? `byorzin-monitor doctor` checks services, screen, hooks, ports and peers.

## Add more computers

1. Install and run `byorzin-monitor setup` on the new computer (**B**).
2. On a computer already in the group (**A**): panel → **Machines** → **Generate code**
   (or `byorzin-monitor pair`).
3. On **B**, type A's address and the code in **Machines** → *I have a code*, or run:

   ```bash
   byorzin-monitor pair 192.168.1.10 482913    # A's IP + the 6-digit code shown on A
   ```

That's it: no tokens copied by hand. Machines on the same LAN also show up under *Found on the
network*; offline machines stay on screen, dimmed. Over Tailscale or WireGuard, pair with the VPN
address. Full guide: [docs/maquinas.md](docs/maquinas.md) (Portuguese).

## Gallery

<p align="center">
  <img src="docs/img/screen.gif" alt="The screen in action: subagents appear, a session waits for you with a yellow frame, a finished task with confetti, then the Byorzin sleeps and dreams" width="720"><br>
  <em>The screen: subagents arrive, someone is waiting for you, a long task finishes, then nap time.</em>
</p>

<p align="center">
  <img src="docs/img/panel.gif" alt="Using the web panel: overview, session details drawer, choosing a layout, pairing code, light theme" width="900"><br>
  <em>The web panel: overview, session details, layouts, pairing and light theme.</em>
</p>

| | |
|---|---|
| ![Cards layout: one column per session, subagents below](docs/img/layout-cards.png) **Cards** | ![Stage layout: Byorzins with speech bubbles](docs/img/layout-palco.png) **Stage** |
| ![Focus layout: the session that needs you, up front](docs/img/layout-foco.png) **Focus** | ![Team layout: org chart with subagents](docs/img/layout-equipe.png) **Team** |
| ![Machines layout: one strip per computer](docs/img/layout-maquinas.png) **Machines** | ![Dashboard layout: totals and tokens per hour](docs/img/layout-dashboard.png) **Dashboard** |
| ![Yellow pulsing frame when a session waits for you](docs/img/scene-alert.png) **Waiting for you** | ![Confetti when a long task finishes](docs/img/scene-done.png) **Finished** |
| ![Byorzin asleep with Zzz](docs/img/scene-sleep.png) **Asleep** | ![Byorzin dreaming about this week's tokens](docs/img/scene-dream.png) **Dreaming** |

<details>
<summary>All nine layouts</summary>

![Mosaic with the nine layouts](docs/img/mosaic.png)
</details>

<details>
<summary>Web panel screenshots</summary>

| | |
|---|---|
| ![Overview](docs/img/panel-overview.png) Overview | ![Session details](docs/img/panel-session.png) Session details |
| ![Layouts](docs/img/panel-layouts.png) Layouts | ![Behavior settings](docs/img/panel-settings.png) Behavior |
| ![Alerts](docs/img/panel-alerts.png) Alerts | ![History](docs/img/panel-history.png) History |
| ![Machines and pairing](docs/img/panel-machines.png) Machines | ![About](docs/img/panel-about.png) About |
| ![Light theme](docs/img/panel-light.png) Light theme | ![Phone](docs/img/panel-mobile.png) Phone |
</details>

## Supported screens

Every backend draws the same frames. Details: [docs/telas.md](docs/telas.md) (Portuguese).

| Screen | Backend | Status |
|---|---|---|
| Any browser: monitor, TV, tablet, phone, Raspberry Pi kiosk (`/tela`) | `web` | **tested** |
| Turing Smart Screen 3.5" rev A (USB `1a86:5722`) | `turing-a` | **tested** |
| Terminal or tmux pane (truecolor half-blocks) | `terminal` | **tested** |
| Linux framebuffer (`/dev/fbN`: Raspberry Pi SPI screens, HDMI without a desktop) | `framebuffer` | tested with a simulated device |
| XuanFang 3.5" rev B | `turing-b` | experimental |
| WeAct Studio Display FS 3.5" / 0.96" | `weact` / `weact-096` | experimental |
| Other USB screens | — | not supported yet (protocol contributions welcome) |

*Experimental* = written from public protocol documentation and unit-tested, but not yet tried on
real hardware. Own one? Run `byorzin-monitor display --backend <name>` and tell us in an issue.

## How it works

```mermaid
flowchart LR
  subgraph W[workstation]
    CW[Claude Code] -- hooks --> KW[collector :8787]
  end
  subgraph L[laptop]
    CL[Claude Code] -- hooks --> KL[collector :8787]
  end
  subgraph S[server]
    CS[Claude Code] -- hooks --> KS[collector :8787]
  end
  KW & KL & KS -- "LAN, group token" --> P[panel :8788<br>draws the frames]
  P --> U[USB screen]
  P --> B[browser /tela]
  P --> T[terminal / framebuffer]
```

Claude Code hooks and the status line write small local events; the collector turns them into
sessions, subagents, tokens and limits; any panel reads all paired collectors and draws the screen.
More: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Features

- **9 layouts** (cards, list, focus, team, grid, stage, activity, dashboard, machines), pinned or
  rotating.
- **Waiting for you**: yellow frame on the screen, browser notification, optional
  [ntfy](https://ntfy.sh) push to your phone.
- **Finished**: confetti when a turn longer than N minutes ends.
- **Weekly and 5-hour limits** with pace projection, per Claude account.
- **History**: ~90 days of tokens per day, model, machine, tools and agents.
- **Idle scenes**: sleepy, asleep, dreaming about your stats, host panel (CPU, RAM, GPU, Ollama,
  Docker).
- **Local LLM**: a Byorzin with headphones while an Ollama model is generating.
- **English and Portuguese** in the panel and on the screen.

Full list: [docs/recursos.md](docs/recursos.md) (Portuguese).

## FAQ

<details>
<summary><b>Does it work with a Claude Pro / Max subscription? And with an API key?</b></summary>

Both. With a subscription, the weekly and 5-hour bars come from what Claude Code passes to the
status line. With an API key there is no subscription limit, so those bars stay empty; sessions,
subagents, tools, tokens and history work the same.
</details>

<details>
<summary><b>Can it show a local LLM?</b></summary>

Yes, Ollama. The collector polls `http://127.0.0.1:11434/api/ps` (configurable with `ollama_url`)
and shows a session while a model is generating.
</details>

<details>
<summary><b>Is the panel safe on my network? What about the token?</b></summary>

On its own computer the panel opens directly. Other devices need the panel link with a key (shown
once, exchanged for an `HttpOnly` cookie), and every change is CSRF-protected. Collectors require
the shared group token, which pairing exchanges for you; the panel key is a different secret.
Traffic is plain HTTP: use it on a trusted LAN or VPN and do not expose the ports to the internet.
</details>

<details>
<summary><b>Does it slow Claude Code down?</b></summary>

No. The hook appends one JSON line per event and exits; the collector does the rest in the
background.
</details>

<details>
<summary><b>How do I uninstall?</b></summary>

`byorzin-monitor uninstall` (add `--purge` to also delete config and data), then
`pipx uninstall byorzin-monitor`.
</details>

## Command line

| Command | What it does |
|---|---|
| `byorzin-monitor setup` | install or update on this computer (`--no-sudo`, `--no-claude`, `-y`) |
| `byorzin-monitor doctor` | diagnose services, screen, hooks, ports and peers |
| `byorzin-monitor status` | sessions and machines at a glance |
| `byorzin-monitor pair [<ip> <code>]` | generate a pairing code, or join another computer's group |
| `byorzin-monitor machines` | paired machines and machines found on the network |
| `byorzin-monitor panel-url` | link to open the panel on another device |
| `byorzin-monitor display --backend <name>` | run a screen in the foreground (`web`, `terminal`, `turing-a`…) |
| `byorzin-monitor uninstall [--purge]` | remove services, udev rule and hooks |

The CLI messages are currently in Portuguese.

## Privacy and security

Recorded: hook event names, tool names, agent types, timestamps, project folder names, session
titles, token counts, model names and rate-limit percentages. **Never** prompts, commands, file
contents or responses. Data stays in local files and on your LAN (plus ntfy pushes, only if you
turn them on). Threat model and how to report a vulnerability: [SECURITY.md](SECURITY.md).

## Documentation

[Architecture](docs/ARCHITECTURE.md) · [Machines and pairing](docs/maquinas.md) ·
[Screens](docs/telas.md) · [Features](docs/recursos.md) · [Changelog](CHANGELOG.md)
(the docs folder is in Portuguese)

## Roadmap

- **More AI coding agents in the same panel** — next up: **OpenAI Codex CLI** (sessions, tools,
  context and its 5h/weekly limits), then other agents with local session data (e.g. Gemini CLI, Aider).
  Each provider gets its own Byorzin color.
- Native layouts for big screens (16:9 monitors and TVs) and portrait displays.
- More USB screens tested on real hardware — help welcome (see `docs/telas.md`).

## Contributing

Bug reports, screens tested on real hardware and new layouts are welcome. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

- Code: [MIT](LICENSE).
- The **Byorzin** mascot (character, name and artwork) is © BYOR-SEC and licensed for use within
  this project only; see [LICENSE-ASSETS.md](LICENSE-ASSETS.md).
- Independent project, not affiliated with or endorsed by Anthropic. "Claude" and "Claude Code"
  are trademarks of Anthropic.
