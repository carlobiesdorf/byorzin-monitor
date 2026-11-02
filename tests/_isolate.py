# Isola os testes reaproveitando o ambiente comum (tests/_env.py), para todos os módulos de
# teste usarem as mesmas pastas temporárias, seja qual for a ordem de importação.
import os

import _env

TEST_DIR = str(_env.TMP)


def free_port(kind="tcp"):
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM if kind == "tcp" else socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p
