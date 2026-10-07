#!/bin/bash
# Лаунчер прошивальщика для Linux/macOS: ищет Python 3.8+ и запускает flash.py.
cd "$(dirname "$0")" || exit 1
export PYTHONUTF8=1

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 8))' 2>/dev/null; then
    PY="$c"; break
  fi
done

if [ -z "$PY" ]; then
  echo "Не найден Python 3.8 или новее."
  case "$(uname)" in
    Darwin) echo "Скачай и установи с https://www.python.org/downloads/ (или: brew install python), потом запусти эту кнопку снова." ;;
    *)      echo "Установи: sudo apt install python3 python3-venv   (или аналог для твоего дистрибутива), потом запусти снова." ;;
  esac
  read -r -p "Нажми Enter, чтобы закрыть… " _
  exit 1
fi

"$PY" flash.py "$@"
code=$?
echo
read -r -p "Нажми Enter, чтобы закрыть окно… " _
exit $code
