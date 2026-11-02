# Contributing

Thanks for helping! Bug reports, screens tested on real hardware, new layouts and translations
are all welcome. Issues and pull requests can be written in English or Portuguese.

## Development setup

```bash
git clone https://github.com/carlobiesdorf/byorzin-monitor && cd byorzin-monitor
python3 -m venv .venv && .venv/bin/pip install -e .
sudo apt install libcairo2 fonts-dejavu-core      # cairosvg and the fonts used on screen
```

Run any part from the checkout with `.venv/bin/byorzin-monitor <subcommand>` or
`python -m byorzin_monitor <subcommand>`.

### Try it without touching your real setup

Every path comes from environment variables, so you can run a throwaway instance next to an
installed one:

```bash
export XDG_CONFIG_HOME=$(mktemp -d) XDG_STATE_HOME=$(mktemp -d) CLAUDE_CONFIG_DIR=$(mktemp -d)
mkdir -p $XDG_CONFIG_HOME/byorzin-monitor
printf 'port = 61787\npanel_port = 61788\ntoken = "dev"\ndiscovery = false\n' > $XDG_CONFIG_HOME/byorzin-monitor/config.toml
byorzin-monitor collector &      # background collector on 61787
byorzin-monitor panel            # http://127.0.0.1:61788 — the Layouts tab has a demo scenario
```

`byorzin-monitor display --backend terminal` or `--backend sim --device /tmp/frame.png` draws the
screen without hardware.

## Tests

```bash
python -m unittest discover -s tests
```

The tests use only the standard library. `tests/_env.py` points `XDG_CONFIG_HOME`,
`XDG_STATE_HOME` and `CLAUDE_CONFIG_DIR` to temporary folders and uses alternative ports, so they
never touch your real configuration, `~/.claude` or running services. Import `_env` (or
`_isolate`) first in any new test module. Serial screens are tested with `_env.FakeSerial`.

CI runs the tests on Python 3.11, 3.12 and 3.13 (`.github/workflows/ci.yml`).

## Style

- Python 3.11+, standard library first. Runtime dependencies are only `pyserial`, `pillow`,
  `numpy` and `cairosvg`; please discuss before adding one.
- The collector, hooks and network code use **only the standard library** — keep it that way.
- Lines up to ~120 characters, 4-space indentation, small functions, no type-checking ceremony.
- Comments and code identifiers are currently mostly in Portuguese; either language is fine for
  new code, but keep one language per comment.
- **Privacy is a feature**: never record prompts, tool inputs/outputs, file contents or
  responses. Hooks keep metadata only.
- The web panel is a single HTML file with plain JavaScript — no build step, no frameworks.
  Every user-visible string must exist in both languages (`L('pt', 'en')` in JS, `data-en`
  attributes in static HTML, `*_EN` tables in `panel/server.py`).
- Text drawn on the screen goes through `i18n.T()`; add the English translation to `i18n.EN`.

## Adding a screen backend

1. Create `byorzin_monitor/display/backends/<name>.py` with a class that subclasses
   `base.Backend` (`byorzin_monitor/display/backends/base.py`):
   - `name`, `label` and `size` (the width × height you want to receive frames in);
   - `show(img, full=False)` receives a PIL image already in `size` and returns how many pixels it
     sent — keep the previous frame and send only what changed;
   - `set_brightness(pct)`, `on()`, `off()` and `close()` when the screen supports them;
   - accept `device=""` (auto-detect) and, for tests, a `ser=` fake serial port;
   - if it was not tested on real hardware, set `experimental = True` and add "[experimental]"
     to the `label`.
2. Register it in `BACKENDS` in `byorzin_monitor/display/backends/__init__.py`. For USB screens
   also add `(vid, pid, serial substring, name, description)` to `KNOWN_USB` — auto-detection,
   `doctor` and the udev rule pick it up from there.
3. Add a test in `tests/` that checks the bytes sent (see `tests/test_usb_extra.py` and
   `tests/test_turing_a.py`).
4. Write original code. Protocol facts can come from anywhere; code from GPL projects cannot be
   copied into this MIT project.
5. Update the table in `docs/telas.md` and in both READMEs.

## Adding a layout

1. Write `layout_<name>(v, t)` in `byorzin_monitor/display/layouts.py`. It receives the merged
   `View` (`v.sessions`, `v.machines`, `v.events`, `v.week_pct`…, see `display/engine.py`) and
   the animation time `t`, and returns a 480×320 image. Start from `base(v)` to get the top bar
   and the compact footer, and reuse helpers like `face()`, `session_look()`, `ctx_bar()` and
   `fit()`.
2. Register it in `LAYOUTS` (end of `layouts.py`) and in `LAYOUT_NAMES`
   (`byorzin_monitor/settings.py`).
3. Add its name and description in both languages to `LAYOUT_INFO` and `LAYOUT_INFO_EN` in
   `byorzin_monitor/panel/server.py`.
4. Check it with the demo scenario (panel → Layouts) and with edge cases: no sessions, one
   session, many sessions, long names, offline machines (see `tests/test_layout_maquinas.py`).
5. Optionally regenerate the README images: `python scripts/readme_images.py`.

## Pull requests

- One topic per pull request, with a short description of what changed and how you tested it.
- Run the tests before opening it.
- For a new screen, say whether it was tested on real hardware and include a photo if you can.
