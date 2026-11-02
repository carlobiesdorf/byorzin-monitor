# hook: chamado pelo Claude Code a cada evento. Grava UMA linha e sai.
# Privacidade: nunca grava prompt, tool_input, tool_response, mensagens nem textos de erro —
# só metadados. Campos de texto livre só entram se forem de uma lista conhecida.
# Leve de propósito (roda a cada evento): só json/os/sys/time, sem importar o resto do pacote.
import json
import os
import sys
import time

KEEP = ("session_id", "hook_event_name", "tool_name", "agent_id", "agent_type")

# valores conhecidos; qualquer outro vira "other" (nunca grava texto livre)
NOTIFICATION_TYPES = {"permission_prompt", "idle_prompt", "auth_success", "elicitation_dialog"}
SOURCES = {"startup", "resume", "clear", "compact"}
REASONS = {"clear", "logout", "prompt_input_exit", "other", "bypass_permissions_disabled", "resume"}
STOP_ERRORS = {"rate_limit", "overloaded", "authentication_failed", "billing_error", "invalid_request",
               "server_error", "api_error", "timeout", "network_error", "context_length_exceeded",
               "max_output_tokens", "permission_error", "not_found", "request_too_large", "unknown"}


def state_dir():
    """Mesma pasta que common.STATE_DIR (repetida aqui para não importar o pacote)."""
    if os.environ.get("XDG_STATE_HOME"):
        return os.path.join(os.environ["XDG_STATE_HOME"], "byorzin-monitor")
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", "byorzin-monitor", "state")
    return os.path.join(os.path.expanduser("~"), ".local", "state", "byorzin-monitor")


def _known(v, allowed):
    if not isinstance(v, str) or not v:
        return None
    return v if v in allowed else "other"


def _error_kind(err):
    if isinstance(err, dict):
        err = err.get("type") or err.get("error")
    return _known(err, STOP_ERRORS)


def event(data, now=None):
    """Linha gravada para um evento (só metadados)."""
    ev = {k: data[k] for k in KEEP if isinstance(data.get(k), str) and data[k]}
    for k in ("tool_name", "agent_type"):
        if k in ev:
            ev[k] = ev[k][:80]
    for k, allowed in (("notification_type", NOTIFICATION_TYPES), ("source", SOURCES), ("reason", REASONS)):
        v = _known(data.get(k), allowed)
        if v:
            ev[k] = v
    ev["ts"] = round(time.time() if now is None else now, 3)
    if data.get("cwd"):
        ev["project"] = os.path.basename(str(data["cwd"]).rstrip("/")) or "/"
    if data.get("hook_event_name") == "StopFailure":
        e = _error_kind(data.get("error"))
        if e:
            ev["error"] = e
    return ev


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(data, dict):
        return 0
    ev = event(data)
    d = state_dir()
    os.makedirs(os.path.join(d, "statusline"), exist_ok=True)
    # O_APPEND: linhas curtas são atômicas mesmo com várias sessões escrevendo ao mesmo tempo
    fd = os.open(os.path.join(d, "events.jsonl"), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, (json.dumps(ev, ensure_ascii=False) + "\n").encode())
    finally:
        os.close(fd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
