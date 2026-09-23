@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "INVOKE=%~dp0scripts\invoke.py"
if not exist "%INVOKE%" set "INVOKE=%~dp0invoke.py"
if not exist "%INVOKE%" (
  echo Cannot find invoke.py. Please re-extract the skill package.
  pause
  exit /b 2
)

set "PYCMD="
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PYCMD=py -3.12" & goto ub_found
py -3.13 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PYCMD=py -3.13" & goto ub_found
py -3 -c "import sys; exit(0 if sys.version_info>=(3,11) else 1)" >nul 2>&1
if not errorlevel 1 set "PYCMD=py -3" & goto ub_found
python -c "import sys; exit(0 if sys.version_info>=(3,11) else 1)" >nul 2>&1
if not errorlevel 1 set "PYCMD=python" & goto ub_found

echo.
echo Python 3.11 or newer is required.
echo Install Python 3.12 from https://www.python.org/downloads/
echo Check "Add python.exe to PATH", then double-click open-console.bat again.
echo.
start https://www.python.org/downloads/
pause
exit /b 2

:ub_found
echo Starting Universal Browser console... A browser tab opens automatically.
echo If an older black window is still running, it will be closed so you get the new version.
echo Keep this window open while you use the console. Close it to stop.
echo Using: %PYCMD%
%PYCMD% "%INVOKE%" ui %*
if errorlevel 1 (
  echo.
  echo The console stopped with an error. See the message above.
  pause
)
