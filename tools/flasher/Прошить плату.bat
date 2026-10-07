@echo off
rem Кнопка для Windows: двойной клик. Ищет Python 3.8+ и запускает flash.py.
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

set PY=
py -3 -c "import sys; sys.exit(sys.version_info < (3, 8))" >nul 2>&1 && set PY=py -3
if not defined PY (
  python -c "import sys; sys.exit(sys.version_info < (3, 8))" >nul 2>&1 && set PY=python
)

if not defined PY (
  echo Не найден Python 3.8 или новее.
  where winget >nul 2>&1
  if not errorlevel 1 (
    echo Пробую поставить автоматически через winget...
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    echo.
    echo Если установка прошла, закрой это окно и запусти кнопку заново.
  ) else (
    echo Скачай и установи с https://www.python.org/downloads/ ^(отметь галочку "Add python.exe to PATH"^),
    echo потом запусти эту кнопку заново.
  )
  pause
  exit /b 1
)

%PY% flash.py %*
echo.
pause
