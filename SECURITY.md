# Security

## Threat model

Byorzin Monitor is designed for a **trusted local network** (home, office) or a private VPN
(Tailscale, WireGuard). It is not designed to be exposed to the internet.

| Component | Port | Exposure | Protection |
|---|---|---|---|
| Collector `/state`, `/history`, `/session` | 8787/TCP | LAN | shared group token (`Authorization: Bearer`) |
| Panel (web UI, previews, `/tela`, its `/api/*`) from **this computer** | 8788/TCP | loopback | none needed: client `127.0.0.1`/`::1` **and** `Host: localhost`/`127.0.0.1` |
| Panel from **another device** on the network | 8788/TCP | LAN | **panel key**: a link `http://IP:8788/?key=…` opened once, exchanged for an `HttpOnly; SameSite=Strict` cookie |
| Panel `/api/sync`, `/api/peers/*` (machine to machine) | 8788/TCP | LAN | shared group token |
| Panel actions (settings, scenes, pairing, remove machine) | 8788/TCP | LAN | authenticated as above **plus** CSRF checks |
| Panel `/api/pair/claim` | 8788/TCP | LAN | 6-digit single-use code, 5-minute lifetime, rate-limited per code, per IP and globally |
| Discovery announcements | 8789/UDP | LAN broadcast | carry name, version, ports and a random id — **never the token** |

### Panel access

- On the machine itself, `http://localhost:8788` opens directly. A request only counts as local if
  it comes from a loopback address **and** the `Host` header is `localhost`/`127.0.0.1`/`::1` (or the
  machine's own IP, from that same IP). A domain that resolves to 127.0.0.1 (DNS rebinding) is
  treated as a network client.
- Other devices need the **panel key**, a random secret created on first start in
  `~/.config/byorzin-monitor/panel_key` (mode 600). It is **not** the group token: leaking the
  panel link does not give access to the collectors. The link is shown only to a browser on the
  machine itself (About tab, `GET /api/panel-url` from localhost, `byorzin-monitor panel-url`).
  Opening it sets a cookie derived from the key (HMAC, not the key itself) and removes the key from
  the address bar. Without a valid cookie the panel answers 401 with instructions.
- **Rotating**: "Generate a new key" in the About tab (only on the machine itself), or delete the
  file. Every link and cookie issued before stops working.
- Machines of the group authenticate to each other's panels with the group token.
- `panel_auth = "off"` restores the old open panel (**insecure**: anyone on the network sees the
  sessions and changes settings). Even then the ntfy topic is not returned to non-local clients.
  `panel_bind = "127.0.0.1"` keeps the panel on this computer only.

### CSRF and browser hardening

- Every state-changing request is a `POST` that must have `Content-Type: application/json`, the
  header `X-Byorzin: 1` and, when the browser sends `Origin`, an `Origin` equal to the `Host`.
  Another web site open in your browser cannot trigger panel actions, read its answers, or make
  the panel send the group token anywhere.
- "Remove machine" only accepts addresses that are already in `peers`; the group token is only
  ever sent to known peers.
- Pages are served with a Content-Security-Policy that only runs scripts with a per-response
  nonce (no inline handlers), `frame-ancestors 'none'` (except `/tela`, which may be embedded), no
  referrer and `nosniff`. Everything that comes from the network (machine names from UDP
  announcements, session titles, project names) is escaped before going into the page.
- Input is validated: bodies over 64 KB are refused (413), wrong types answer 400, colors must be
  `#rrggbb`, the ntfy server must be `http(s)://`.
- `/tela/stream.mjpg` accepts at most 4 simultaneous clients, each for up to 2 hours; stalled
  clients are dropped after 15 s.

### What this means in practice

- **Someone on your LAN without the panel link sees nothing** but a page explaining how to get it.
  Anyone **with** the link (or a device that opened it) can see your sessions (titles, project
  folder names, machines, token counts, history), change screen settings including ntfy, pair and
  remove machines. Treat the link like a password; share it only with your own devices.
- **Traffic is plain HTTP.** The token, the panel key and the cookie travel unencrypted on the
  LAN, including the token once during pairing. Someone able to sniff your LAN can capture them.
  Cookies are not isolated by port: other web services on the same IP receive the panel cookie.
- The token in `~/.config/byorzin-monitor/config.toml` gives read access to every collector of the
  group and lets the holder push settings to every panel.
- Settings replicate between panels by a revision counter (`rev`), not by wall-clock time.
- `setup` modifies `~/.claude/settings.json` (with a diff, confirmation and a backup) so that
  Claude Code runs `byorzin-monitor hook` and `byorzin-monitor statusline`. Treat write access to
  that file, and to the installed package, as code execution in your Claude Code sessions.
- With sudo, `setup` installs a udev rule and a system service that runs the display as your user
  when a known USB screen is plugged in.

## Recommendations

- **Firewall**: allow 8787/TCP, 8788/TCP and 8789/UDP only from your LAN or VPN interface.
  `byorzin-monitor setup` does this automatically when `ufw` is active (`--lan` picks the
  network, `192.168.0.0/16` by default). Never forward these ports on your router.
- Do not use it on public or shared Wi-Fi.
- To keep the collector local only, set `bind = "127.0.0.1"` in `config.toml` (then other machines
  cannot read it); `panel_bind = "127.0.0.1"` does the same for the panel.
- Keep `panel_auth = "lan"` (the default). If a device with the panel link is lost, generate a new
  panel key.
- If a machine of the group is compromised or lost, generate a new token (`token = "..."` in the
  `config.toml` of one machine) and pair the others again. Removing a machine does not rotate it.
- Use a hard-to-guess ntfy topic, or your own ntfy server. ntfy messages contain only the project
  folder name, the machine and the reason — never the session title. The topic is only shown to
  authenticated panel clients.

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's private vulnerability
reporting ("Report a vulnerability" under the repository's **Security** tab) with:

- a description of the issue and its impact;
- steps to reproduce (version from `byorzin-monitor --version`, OS, configuration);
- any suggested fix.

You should get a first answer within a few days. Fixes are released as a new version and noted in
[CHANGELOG.md](CHANGELOG.md); reporters are credited if they wish.

## Supported versions

Only the latest released version receives security fixes.
