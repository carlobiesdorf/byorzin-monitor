# Architecture

Byorzin Monitor has four moving parts per machine, all in one Python package
(`byorzin_monitor`) and one command (`byorzin-monitor <subcommand>`).

```
                         one machine                                      other paired machines
 ┌──────────────────────────────────────────────────────────────┐        ┌────────────────────┐
 │  Claude Code                                                 │        │  collector :8787   │
 │   ├─ hooks ──────────► hook  ─► events.jsonl (1 line/event)  │        │  panel     :8788   │
 │   └─ status line ────► statusline ─► rate.json, statusline/  │        └─────────▲──────────┘
 │                                                              │                  │ GET /state
 │  ~/.claude/sessions/*.json   (live sessions)                 │                  │ (Bearer token)
 │  ~/.claude/projects/**.jsonl (transcripts → token counts)    │                  │
 │                 │                                            │                  │
 │                 ▼                                            │                  │
 │  collector :8787  ── GET /state, /history, /session ─────────┼──────────────────┤
 │   sessions, subagents, alerts, limits, tokens, host metrics, │                  │
 │   Ollama, history.json; UDP announce on :8789                │                  │
 │                 │                                            │                  │
 │                 ▼  (local + every peer)                      │                  │
 │  Fetcher ─► View ─► Director ─► scenes / layouts ─► frame 480×320                │
 │                                           │                                     │
 │      ┌────────────────┬──────────────────┼──────────────────┐                   │
 │      ▼                ▼                  ▼                  ▼                   │
 │  display (USB)   panel :8788 /tela   terminal         framebuffer               │
 │  udev → systemd  browser, MJPEG      ▀ truecolor      /dev/fbN                  │
 │                                                                                 │
 │  panel :8788: settings (display.json) ── POST /api/sync ──► peers' panels ──────┘
 └──────────────────────────────────────────────────────────────┘
```

## 1. Capture: hooks and status line

- `hooks/hook.py` is registered for the Claude Code hook events. It reads the event JSON from
  stdin, keeps **only metadata** (event name, session id, tool name, agent type, notification
  type, short error type, project folder name, timestamp) and appends one line to `~/.local/state/byorzin-monitor/events.jsonl`.
  It never writes `prompt`, `tool_input`, `tool_response` or messages.
- `hooks/statusline.py` is the Claude Code status line. It stores the account rate limits
  (weekly and 5-hour windows, when present) in `rate.json`, one snapshot per Claude account
  (`account.py`: derived id + short label from `oauthAccount` in `.claude.json`, never the e-mail
  or uuid), and per-session info (model, context usage, cost, account) in `statusline/`, then
  prints a short line — or the output of the previous status line, which is chained.
- `claude_settings.py` installs and removes both in `~/.claude/settings.json` (diff, confirmation,
  backup, idempotent).

## 2. Collector (`collector.py`, port 8787)

Always running (systemd user service). It combines:

- live sessions from `~/.claude/sessions/*.json` (checked against running PIDs);
- the events file → per-session status (working / waiting / idle / error / limit), current tool
  and running subagents;
- transcripts in `~/.claude/projects/` → token counts per hour, per model and per session
  (read incrementally by offset);
- `rate.json` → weekly and 5-hour usage per account (`/state`: `account`, `rates`, and the old
  `rate` = this machine's account, for older peers; see `docs/maquinas.md`, "Várias contas");
- host metrics (CPU, RAM, GPU via `nvidia-smi`, Docker), `ollama.py` (local LLM session),
  `alerts.py` ("waiting for you" and "finished", ntfy), `history.py` (daily aggregates, 90 days),
  `details.py` (recent events per session).

It serves `GET /state`, `GET /history?days=N` and `GET /session?id=...`, all requiring
`Authorization: Bearer <token>`. It uses only the standard library.

## 3. Rendering (`display/`)

- `engine.Fetcher` polls `/state` from the local collector and every peer every 2 s, corrects
  clock skew and keeps the last known state of machines that went offline (`seen.json`).
- `engine.View` merges all machines into one view: sessions sorted by urgency, limits, tokens,
  events, machines.
- `engine.Director` picks the scene for each frame: work layout (or rotation), wake-up when a new
  session appears, limit alert, celebration, idle → sleepy → asleep → dreaming, host panel, or
  forced scenes for tests.
- `scenes.py`, `layouts.py` and `effects.py` draw a 480×320 Pillow image. `mascot.py` renders the
  Byorzin from SVG with cairosvg (cached per mood, size, fatness and color). `i18n.py` translates
  the drawn text (`language` setting).
- `engine.Renderer` ties it together and is shared by every output.

## 4. Outputs (`display/backends/`)

Each backend subclasses `base.Backend` and receives frames already scaled to its `size`
(`engine.fit_to` scales with letterboxing and rotates for portrait outputs). USB backends send
only the changed region. `backends/__init__.py` holds the registry (`BACKENDS`), the known USB IDs
(`KNOWN_USB`) used for auto-detection, `doctor` and the udev rule.

The `web` backend is special: the **panel** renders frames itself (one render per frame, shared by
all browsers) and serves `/tela` (full-screen page), `/tela/frame.jpg` and `/tela/stream.mjpg`.

## 5. Panel (`panel/server.py`, port 8788)

A single-page app (`panel/static/index.html`, no build step, no dependencies) plus a small JSON
API: state, settings, previews of layouts and scenes (demo or real data), history across machines,
session details, pairing. Settings are saved to `display.json` and pushed to every peer's panel
(`POST /api/sync`, token required; newest `updated_at` wins), so the screen behaves the same on
any machine.

## 6. Multiple machines (`network.py`, `pairing.py`)

- **Discovery**: each collector announces itself by UDP broadcast on port 8789 (name, version,
  ports, random install id — never the token).
- **Pairing**: machine A generates a 6-digit single-use code valid for 5 minutes; machine B sends
  it to A's panel (`/api/pair/claim`) and receives the group token and peer list. Attempts are
  rate-limited per code, per IP and globally. A tells its existing peers about B.
- `config.toml` (token, peers) is re-read live by the collector, panel and display.

## Files

| Path | Content |
|---|---|
| `~/.config/byorzin-monitor/config.toml` | token, peers, ports, hostname, backend (mode 600) |
| `~/.config/byorzin-monitor/display.json` | screen/panel settings (replicated to peers) |
| `~/.config/byorzin-monitor/machines.json`, `install_id` | paired machine metadata, own id |
| `~/.local/state/byorzin-monitor/events.jsonl` | hook events (metadata only) |
| `~/.local/state/byorzin-monitor/rate.json`, `statusline/` | limits and per-session info from the status line |
| `~/.local/state/byorzin-monitor/tokens.json`, `history.json` | token counters and daily history |
| `~/.local/state/byorzin-monitor/seen.json`, `frame.png` | last known state of machines, current frame |
