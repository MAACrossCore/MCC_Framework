@echo off
setlocal
cd /d "%~dp0.."

set "PY="
if exist "%~dp0..\python\python.exe" (
  "%~dp0..\python\python.exe" "%~dp0ensure_mumu.py" %*
  exit /b %ERRORLEVEL%
)

where py >nul 2>&1 && (
  py -3 "%~dp0ensure_mumu.py" %*
  exit /b %ERRORLEVEL%
)

where python >nul 2>&1 && (
  python "%~dp0ensure_mumu.py" %*
  exit /b %ERRORLEVEL%
)

echo [MuMu pretask] Python not found. Re-download the latest release package or install Python 3.10+.
exit /b 1
