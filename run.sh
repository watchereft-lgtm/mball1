#!/usr/bin/env bash
# run.sh — запуск «Магического шара предсказаний» (Linux и macOS).
#
#   ./run.sh                  запуск на порту 8501
#   ./run.sh --port 8600      другой порт
#   ./run.sh --ip 192.168.1.5 вручную указать адрес для QR-кода
#
# Зависимости берутся из .pylibs рядом с этим файлом. Если её нет — сначала ./setup.sh
set -euo pipefail

cd "$(dirname "$0")"

PORT=8501
IP=""

while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="${2:?нужен номер порта}"; shift 2 ;;
    --ip)   IP="${2:?нужен адрес}"; shift 2 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "Неизвестный параметр: $1" >&2; exit 2 ;;
  esac
done

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

if [ ! -d ".pylibs" ]; then
  echo "Папка .pylibs не найдена. Выполните один раз ./setup.sh" >&2
  exit 1
fi

export PYTHONPATH="$PWD/.pylibs"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

if [ -z "$IP" ]; then
  IP="$("$PYTHON" -X utf8 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.connect(('8.8.8.8', 80))
    print(s.getsockname()[0])
except OSError:
    print('')
finally:
    s.close()
" 2>/dev/null || true)"
fi

echo "$PORT" > .port

LINK="http://127.0.0.1:${PORT}/?screen=game"
[ -n "$IP" ] && LINK="http://${IP}:${PORT}/?screen=game"

echo
echo "  Магический шар предсказаний"
echo "  Витрина с QR-кодом : http://127.0.0.1:${PORT}/"
echo "  Игра для телефона  : ${LINK}"
[ -z "$IP" ] && echo "  Внимание: локальный адрес не найден, укажите вручную: ./run.sh --ip 192.168.0.10"
echo
echo "  Остановить сервер: Ctrl+C"
echo

exec "$PYTHON" -m streamlit run app.py \
  --global.developmentMode false \
  --server.address 0.0.0.0 \
  --server.port "$PORT" \
  --server.headless true \
  --browser.gatherUsageStats false \
  --client.showErrorDetails full \
  --theme.base light
