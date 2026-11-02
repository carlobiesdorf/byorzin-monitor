# statusline: status line do Claude Code. Guarda os limites da conta (rate_limits) e
# dados da sessão para o coletor, e imprime uma linha curta (ou a da status line encadeada).
import json
import re
import sys
import time

from byorzin_monitor.common import RATE_FILE, SESSION_INFO_DIR, ensure_state_dir, load_config, read_json, write_json_atomic


def fmt_pct(v):
    return f"{v:.0f}%" if isinstance(v, (int, float)) else "?"


def _obj(x):
    """Campo que deveria ser objeto: qualquer outra coisa vira {} (entrada inesperada não pode quebrar)."""
    return x if isinstance(x, dict) else {}


def _num(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


RATE_KEEP = 8 * 86400        # conta sem notícia há mais que isso sai do rate.json


def _save(data, now):
    from byorzin_monitor.account import identify, rate_accounts
    acc = identify()
    rl = _obj(data.get("rate_limits"))
    if rl.get("seven_day") or rl.get("five_hour"):
        raw = read_json(RATE_FILE, {}) or {}
        accs = rate_accounts(raw, acc["id"])
        prev = accs.get(acc["id"]) or {}
        snap = {"seen_at": now, "label": acc["label"]}
        for k in ("seven_day", "five_hour"):
            w, p = _obj(rl.get(k)), prev.get(k)
            pct = _num(w.get("used_percentage"))
            if pct is not None:
                cur = {"pct": pct, "resets_at": _num(w.get("resets_at"))}
                # várias sessões escrevem aqui; uma parada pode ter valor velho. Na mesma janela
                # (mesmo resets_at) o uso só sobe; janela nova (resets_at maior) sempre vale.
                # Tudo isso por conta: cada conta tem a sua janela.
                if p and p.get("resets_at") == cur["resets_at"] and p.get("pct", 0) > cur["pct"]:
                    cur = p
                elif p and (p.get("resets_at") or 0) > (cur["resets_at"] or 0):
                    cur = p
                snap[k] = cur
            elif p:
                snap[k] = p
        if "accounts" in raw and snap.get("seven_day") == prev.get("seven_day") \
                and snap.get("five_hour") == prev.get("five_hour") and snap["label"] == prev.get("label") \
                and prev.get("seen_at") and now - prev["seen_at"] < 60:
            pass   # nada novo: não regrava a cada atualização de cada sessão
        else:
            accs = {k: v for k, v in accs.items() if now - (_num(v.get("seen_at")) or 0) < RATE_KEEP}
            accs[acc["id"]] = snap
            write_json_atomic(RATE_FILE, {"v": 2, "accounts": accs})

    sid = data.get("session_id")
    if isinstance(sid, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", sid):   # vira nome de arquivo
        cw, cost, name = _obj(data.get("context_window")), _obj(data.get("cost")), data.get("session_name")
        write_json_atomic(SESSION_INFO_DIR / f"{sid}.json", {
            "ts": now,
            "model": _obj(data.get("model")).get("display_name"),
            "title": name[:60] if isinstance(name, str) and name.strip() else None,
            "context_pct": _num(cw.get("used_percentage")),
            "cost_usd": _num(cost.get("total_cost_usd")),
            "lines_added": _num(cost.get("total_lines_added")),
            "lines_removed": _num(cost.get("total_lines_removed")),
            "account": acc["id"],
        })


def main():
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    now = time.time()
    try:
        ensure_state_dir()
        _save(data, now)
    except Exception as e:      # a linha de status do Claude nunca pode quebrar por causa do monitor
        print(f"byorzin-monitor statusline: {e!r}", file=sys.stderr)
    rl = _obj(data.get("rate_limits"))

    chain = load_config().get("statusline_chain")
    if chain:
        try:
            import subprocess
            out = subprocess.run(chain, shell=True, input=raw, capture_output=True, text=True, timeout=5).stdout
            sys.stdout.write(out)
            return 0
        except Exception:
            pass
    model = _obj(data.get("model")).get("display_name") or ""
    ctx = _num(_obj(data.get("context_window")).get("used_percentage"))
    parts = [str(model), f"ctx {fmt_pct(ctx)}" if ctx is not None else ""]
    sd = _num(_obj(rl.get("seven_day")).get("used_percentage"))
    fh = _num(_obj(rl.get("five_hour")).get("used_percentage"))
    if sd is not None:
        parts.append(f"semana {fmt_pct(sd)}")
    if fh is not None:
        parts.append(f"5h {fmt_pct(fh)}")
    print(" · ".join(p for p in parts if p))
    return 0


if __name__ == "__main__":
    sys.exit(main())
