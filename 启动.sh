#!/bin/bash
cd "$(dirname "$0")" || exit 1
PY=python3
[ -x ".venv/bin/python" ] && PY=".venv/bin/python"
if ! "$PY" -c "import imgui_bundle" 2>/dev/null; then
  echo "  第一次要先装依赖…"; bash setup.sh || exit 1; PY=".venv/bin/python"
fi
exec "$PY" app/main.py "$@"
