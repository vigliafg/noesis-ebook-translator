#!/usr/bin/env bash
# Launch Noesis Ebook Translator quickly.
#
#   ./run-tr.sh                    # start the desktop app
#   ./run-tr.sh some_book.epub     # (args are forwarded to main.py)
#
# It uses the project virtualenv if present, otherwise the system python3.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

if [[ -x ".venv/bin/python" ]]; then
    PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PY="python3"
else
    echo "error: no python3 found" >&2
    exit 1
fi

# Optional: force the reader backend, e.g.
#   NOESIS_READER_BACKEND=full ./run-tr.sh

exec "$PY" main.py "$@"
