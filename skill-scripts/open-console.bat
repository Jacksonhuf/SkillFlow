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
echo Closing stale console on port 8765 if any...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8765" ^| findstr "LISTENING"') do (
  if not "%%p"=="0" taskkill /F /T /PID %%p >nul 2>&1
)
ping -n 2 127.0.0.1 >nul
echo Starting Universal Browser console on port 8771...
echo Do NOT use old http://127.0.0.1:8765/ tabs - they may still ask for a token.
echo Keep this window open while you use the console. Close it to stop.
echo Using: %PYCMD%
%PYCMD% "%INVOKE%" ui %*
if errorlevel 1 (
  echo.
  echo The console stopped with an error. See the message above.
  pause
)
