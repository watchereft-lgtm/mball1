#!/usr/bin/env bash
# setup.sh — один раз скачать зависимости в .pylibs (Linux и macOS).
#
#   ./setup.sh            скачать то, чего не хватает
#   ./setup.sh --clean    удалить .pylibs и скачать заново
set -euo pipefail

cd "$(dirname "$0")"

find_python() {
  for candidate in "${DSH_PYTHON:-}" "./.venv/bin/python" python3 python; do
    if [ -n "$candidate" ] && command -v "$candidate" >/dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
  done
  echo "Python не найден. Установите Python 3.10+." >&2
  return 1
}

PYTHON="$(find_python)"
echo "Python: $PYTHON"
export PYTHONUTF8=1
exec "$PYTHON" -X utf8 setup_deps.py "$@"
