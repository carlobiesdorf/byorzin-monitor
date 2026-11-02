# Quadros fixos (demo, relógio congelado) usados por tests/test_hd.py para conferir que a tela
# USB (escala 1) continua byte a byte igual e que a escala alta não desalinha nada.
import os
import time
from contextlib import ExitStack, contextmanager
from datetime import datetime
from unittest import mock

FIXED = 1793000000.0          # instante fixo (o relógio da tela e as durações não mudam)
T = 12.3                      # tempo da animação


class _DT(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls.fromtimestamp(FIXED, tz)


@contextmanager
def frozen():
    """Relógio parado, fuso UTC, idioma pt-BR e estado global zerado."""
    from byorzin_monitor import i18n
    from byorzin_monitor.display import layouts as L, scenes as S
    old_tz = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time.tzset()
    try:
        with ExitStack() as st:
            st.enter_context(mock.patch("time.time", return_value=FIXED))
            st.enter_context(mock.patch.object(S, "datetime", _DT))
            st.enter_context(mock.patch.object(L, "datetime", _DT))
            i18n.set_lang("pt-BR")
            S.set_colors({})
            L._Focus.idx, L._Focus.until = 0, 0
            yield
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        time.tzset()


def frames():
    """{nome: função sem argumentos que desenha o quadro} — todos os layouts e cenas."""
    from byorzin_monitor.display import effects as E, layouts as L, scenes as S
    from byorzin_monitor.display.demo import demo_view

    def v():
        L._Focus.idx, L._Focus.until = 0, 0
        return demo_view({})

    def dream():
        x = v()
        x.dream = ("31M", "tokens em 02/11", "recorde do dia!")
        return S.scene_idle(x, T, "dream")

    def host():
        x = v()
        return S.scene_host(x, T, *x.metrics[0])

    out = {f"layout-{n}": (lambda f=f: f(v(), T)) for n, f in L.LAYOUTS.items()}
    out.update({
        "idle-awake": lambda: S.scene_idle(v(), T, "awake"),
        "idle-sleepy": lambda: S.scene_idle(v(), T, "sleepy"),
        "idle-sleep": lambda: S.scene_idle(v(), T, "sleep"),
        "idle-dream": dream,
        "wake": lambda: S.scene_wake(v(), T, v().sessions[0]),
        "limit": lambda: S.scene_limit(v(), T),
        "host": host,
        "done": lambda: E.scene_done(v(), T, {"label": "api", "host": "server", "worked_s": 1380}),
        "alert": lambda: E.alert_frame(L.layout_cards(v(), T), T),
        "llm-face": lambda: L.layout_cards(_with_llm(v()), T),
    })
    return out


def _with_llm(v):
    v.sessions[0] = {**v.sessions[0], "kind": "llm"}
    return v


def digests():
    import hashlib
    out = {}
    with frozen():
        for n, f in frames().items():
            im = f()
            out[n] = hashlib.sha256(im.mode.encode() + repr(im.size).encode() + im.tobytes()).hexdigest()[:20]
    return out


if __name__ == "__main__":
    import _env  # noqa: F401
    for k, h in digests().items():
        print(f'    "{k}": "{h}",')
