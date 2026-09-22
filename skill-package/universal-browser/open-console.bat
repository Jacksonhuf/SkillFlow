@echo off
setlocal
rem Universal Browser - double-click to open the local console.
rem Works both from the skill root (scripts\invoke.py) and from inside scripts\.
cd /d "%~dp0"
set "INVOKE=%~dp0scripts\invoke.py"
if not exist "%INVOKE%" set "INVOKE=%~dp0invoke.py"
if not exist "%INVOKE%" (
  echo Cannot find invoke.py next to this launcher. Please re-extract the skill package.
  pause
  exit /b 2
)

set "PYCMD="
where py >nul 2>nul && set "PYCMD=py -3"
if not defined PYCMD where python >nul 2>nul && set "PYCMD=python"
if not defined PYCMD (
  echo Python 3.12+ is required. Install it from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH", then double-click this file again.
  start https://www.python.org/downloads/
  pause
  exit /b 2
)

echo Starting Universal Browser console... A browser tab opens automatically.
echo Keep this window open while you use the console. Close it to stop.
%PYCMD% "%INVOKE%" ui %*
if errorlevel 1 (
  echo.
  echo The console stopped with an error. See the message above.
  pause
)
