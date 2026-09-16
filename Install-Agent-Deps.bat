@echo off
setlocal
cd /d "%~dp0"

set "PY="
if exist "%~dp0python\python.exe" set "PY=%~dp0python\python.exe"
if not defined PY where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"

if not defined PY (
  echo [ERROR] Python not found. Re-download the latest release package or install Python 3.10+.
  pause
  exit /b 1
)

echo Using: %PY%
REM Pin in agent\requirements.txt (maafw==x.y.z) must match bundled MaaFramework.
REM --force-reinstall so a newer wrong binding can be downgraded to the pin.
%PY% -m pip install --upgrade --force-reinstall -r "%~dp0agent\requirements.txt" --find-links "%~dp0deps" --no-index --no-warn-script-location
if errorlevel 1 (
  echo Local deps install failed, trying online mirrors...
  %PY% -m pip install --upgrade --force-reinstall -r "%~dp0agent\requirements.txt" --no-warn-script-location
)
if errorlevel 1 (
  echo [ERROR] pip install failed.
  pause
  exit /b 1
)

echo.
echo Agent deps installed. Start MFAAvalonia.exe next.
if not exist "%~dp0config\orders_source.json" (
  echo Tip: for order-friend tasks, copy config\orders_source.example.json
  echo      to config\orders_source.json and set your url.
)
pause
exit /b 0
