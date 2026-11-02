#!/usr/bin/env bash
# Instalação a partir do repositório clonado (alternativa ao `pipx install git+https://github.com/carlobiesdorf/byorzin-monitor`).
# Cria uma venv em .venv, instala o pacote e roda o assistente:  ./install.sh [opções do setup]
set -euo pipefail
REPO="$(cd "$(dirname "$0")" && pwd)"
python3 -c 'import sys; assert sys.version_info >= (3, 11), "precisa de Python >= 3.11"'
python3 -m venv --help >/dev/null 2>&1 || { echo "instale: sudo apt install python3-venv"; exit 1; }
[ -x "$REPO/.venv/bin/python" ] || python3 -m venv "$REPO/.venv"
"$REPO/.venv/bin/pip" install -q --upgrade pip
"$REPO/.venv/bin/pip" install -q -e "$REPO"
exec "$REPO/.venv/bin/byorzin-monitor" setup "$@"
