@echo off
call "%~dp0..\..\agent\ensure_mumu.cmd" %*
exit /b %ERRORLEVEL%
