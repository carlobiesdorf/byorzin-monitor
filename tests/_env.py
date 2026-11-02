# Isola os testes: XDG e CLAUDE_CONFIG_DIR em pastas temporárias e portas alternativas,
# antes de qualquer import de byorzin_monitor (common.py lê o ambiente na importação).
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

if "BYORZIN_TEST_TMP" not in os.environ:
    TMP = Path(tempfile.mkdtemp(prefix="byorzin-test-"))
    os.environ["BYORZIN_TEST_TMP"] = str(TMP)
    os.environ["XDG_CONFIG_HOME"] = str(TMP / "config")
    os.environ["XDG_STATE_HOME"] = str(TMP / "state")
    os.environ["CLAUDE_CONFIG_DIR"] = str(TMP / "claude")
    for d in ("config/byorzin-monitor", "state/byorzin-monitor", "claude/sessions", "claude/projects"):
        (TMP / d).mkdir(parents=True, exist_ok=True)
    (TMP / "config/byorzin-monitor/config.toml").write_text(
        'port = 58797\npanel_port = 58798\nbind = "127.0.0.1"\ntoken = "teste"\nhostname = "maq-teste"\n')
    # conta do Claude: nunca cai no ~/.claude.json de verdade (sem oauthAccount = "API key")
    (TMP / "claude/.claude.json").write_text("{}")
    atexit.register(shutil.rmtree, TMP, True)
TMP = Path(os.environ["BYORZIN_TEST_TMP"])
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class FakeSerial:
    """Porta serial falsa: guarda o que foi escrito e devolve respostas programadas."""

    def __init__(self, replies=b""):
        self.out = bytearray()
        self.replies = bytearray(replies)
        self.is_open = True

    def write(self, b):
        self.out += bytes(b)
        return len(b)

    def read(self, n=1):
        r, self.replies = bytes(self.replies[:n]), self.replies[n:]
        return r

    def flush(self):
        pass

    def reset_input_buffer(self):
        pass

    def reset_output_buffer(self):
        pass

    def close(self):
        self.is_open = False
