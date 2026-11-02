# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Planned
- OpenAI Codex CLI as a second provider (sessions, tools, context, 5h/weekly limits).

## [0.9.0] — first public release

### Hardening before the release
- Machines with the same hostname no longer disappear: collectors now send a stable `install_id`
  and `served_at` in `/state`, `/session` and `/history`; the display de-duplicates by installation
  (one machine reached through two URLs shows once) and names clashes `raspberrypi`, `raspberrypi (2)`.
- Clock-skew correction uses `served_at` (the moment of the reply) instead of the state's `ts`.
- Out-of-order hook events no longer flip a session back to an older status or resurrect finished
  subagents (tombstones); late events of an ended session are ignored.
- A permission request or waiting notification from inside a subagent now marks the session as
  "waiting for you" (and the subagent too) without giving the subagent's tool to the session.
- Hook privacy: tool error text is never stored; `StopFailure` stores only a known error kind;
  `reason`, `source` and `notification_type` only from known lists (otherwise `other`).
- An invalid `config.toml` no longer crashes the status line, collector, panel or CLI: defaults plus
  whatever can be read are used, the error is logged once, and `doctor` reports the line.
- `config.toml` writes (pairing, setup, status line chaining) re-serialize the whole file from
  `tomllib` (multi-line arrays, escapes, sections and unknown keys preserved; only the top comment
  block is kept).
- `uninstall` restores the previous Claude Code status line.
- Token counter: keeps the most recent message ids (ordered), forgets offsets of deleted
  transcripts and reads large transcripts in blocks.
- Daily history no longer freezes on the first day of a new installation; today always follows `/state`.
- Host metrics use `ollama_url` from the config.
- Screen: no overlapping "+N sessions" labels with many sessions (team, activity, dashboard),
  long host lists in the top bar, emoji removed from titles (they rendered as boxes), the first frame
  (and any forced layout) never shows the limit scene, singular/plural and "just now" texts.
- CLI: clear one-line errors with non-zero exit codes (no screen, unknown backend/layout, missing
  serial device, port already in use, unknown options); `display --help` lists backends and layouts.

### Also in this release
- Several Claude accounts: each machine identifies the logged-in account (`oauthAccount` in
  `.claude.json`; only a derived id and a short label leave the machine, never the e-mail or uuid)
  and the usage limits are kept per account (`rate.json` v2, `/state` `account`/`rates`, old `rate`
  kept for older peers). With one account nothing changes; with 2+ the screen shows one bar per
  account (top bar and footers, up to 3, then `+N`), the limit alert fires for any account and
  names it, sessions show their account where the machine is shown, and the panel shows per-account
  week/5h, the account of each machine and session, and lets you rename accounts
  (`account_labels`, replicated). API-key users show as "API key" without limits. Demo scenario
  with 2 accounts in the panel.
- Lightweight entry point: `hook`/`statusline` start without loading the CLI (~125 ms → ~55 ms per
  event on the test machine, most of it the Python interpreter itself).
- `display --backend framebuffer --device file --size 480x320 --bpp 16` to test without hardware.
- `byorzin-monitor panel-url` prints the panel link to open on another device.
- Setup detects the LAN subnet for the firewall, passes `XDG_*`/`CLAUDE_CONFIG_DIR` to the units,
  quotes paths with spaces, works without `systemctl` and warns about legacy units with `--no-sudo`.
- `hostname` is re-read from `config.toml` without restarting.


### Capture and collection
- `hook` and `statusline` commands for Claude Code: one metadata-only line per hook event (never
  prompts, tool inputs/outputs or answers); account limits (weekly and 5-hour windows) and
  per-session model, context usage and cost from the status line, chaining an existing status line.
- Collector service (port 8787, token required): live sessions, status (working, waiting,
  idle, error, limit), current tool, background subagents, token counts from transcripts
  (per hour, model and session), host metrics (CPU, RAM, GPU, Docker).
- Alerts: "waiting for you" (permission requests, questions, idle prompts) and "finished"
  (turns longer than N minutes), de-duplicated across machines, with optional ntfy push.
- Daily history for ~90 days: tokens per day and model, sessions, time working, your messages,
  tools used and agents started.
- Local LLM: an Ollama model that is generating shows up as a special session.

### Screens
- 480×320 renderer shared by every output, with automatic scaling and rotation.
- Backends: Turing Smart Screen 3.5" rev A (tested), browser page `/tela` with JPEG/MJPEG
  endpoints (tested), terminal in truecolor (tested), Linux framebuffer, PNG simulator, and
  experimental XuanFang rev B and WeAct Studio Display FS 3.5"/0.96".
- Auto-detection of known USB screens; udev rule starts the display when the screen is plugged in.
- Nine work layouts: cards, list, focus, team, grid, stage, activity, dashboard and machines;
  optional rotation between layouts.
- Scenes: awake, sleepy, asleep, dreaming about statistics, startled by a new session, limit
  alert, host panel, pulsing "waiting for you" frame and "finished" celebration.
- The Byorzin gets fatter with weekly (or 5-hour) usage; each machine gets a deterministic neon
  color from its name, changeable in the panel.
- Context usage bar for every session; weekly pace projection.
- `language` setting: screen text in Brazilian Portuguese or English.

### Panel (port 8788)
- Live view of the screen, sessions, limits and tokens; session details (model, context,
  cost, subagents, recent events).
- Layout and scene previews with a demo scenario or real data, "test on screen" for 15 s.
- Settings replicated to every paired machine; brightness and night hours; browser notifications
  and sound.
- History charts across all machines.
- Bilingual interface (English and Brazilian Portuguese), remembered per browser.

### Multiple machines
- Pairing with a 6-digit single-use code (5 minutes, rate-limited), from the panel or
  `byorzin-monitor pair`; the group token and peer list are shared automatically.
- Discovery on the local network by UDP broadcast (port 8789, never carries the token).
- Offline machines stay visible with their last known state and "seen … ago".

### Command line and packaging
- `byorzin-monitor setup | doctor | status | pair | machines | uninstall | display`.
- `setup` installs systemd user services, the udev rule and display service, ufw rules for the
  LAN and the Claude Code hooks (with diff, confirmation and backup); migrates the earlier
  `claude-monitor` installation.
- Installable with pipx or `./install.sh`; MIT license.
