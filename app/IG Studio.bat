@echo off
rem IG Studio for Windows. Double-click to start. Stop it from Settings > Quit in the app.
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
if !errorlevel! equ 0 set "PY=py -3"
if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
  if !errorlevel! equ 0 set "PY=python"
)

if not defined PY (
  echo.
  echo   IG Studio needs Python 3.9 or newer.
  echo.
  echo   Install it with:   winget install Python.Python.3.12
  echo   or download it from https://www.python.org/downloads/windows/
  echo   ^(tick "Add python.exe to PATH" in the installer^), then double-click IG Studio again.
  echo.
  start "" "https://www.python.org/downloads/windows/"
  pause
  exit /b 1
)

rem Prefer pythonw so no console window lingers.
set "PYW="
for /f "usebackq delims=" %%i in (`!PY! -c "import sys, os; print(os.path.join(os.path.dirname(sys.executable), 'pythonw.exe'))"`) do set "PYW=%%i"
if defined PYW if exist "!PYW!" (
  start "" "!PYW!" "%~dp0server.py"
  exit /b 0
)

echo Starting IG Studio. Keep this window open; close it to stop.
!PY! "%~dp0server.py"
