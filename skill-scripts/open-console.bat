@echo off
setlocal EnableExtensions
rem Universal Browser - double-click to open the local console.
cd /d "%~dp0"
set "INVOKE=%~dp0scripts\invoke.py"
if not exist "%INVOKE%" set "INVOKE=%~dp0invoke.py"
if not exist "%INVOKE%" (
  echo Cannot find invoke.py next to this launcher. Please re-extract the skill package.
  pause
  exit /b 2
)

set "PYCMD="
rem Prefer Python 3.12+ via the Windows py launcher (works when 3.11 is the default "py -3").
for %%V in (3.13 3.12) do (
  py -%%V -c "import sys" >nul 2>&1
  if not errorlevel 1 set "PYCMD=py -%%V" & goto :found
)
where py >nul 2>&1
if not errorlevel 1 (
  py -3 -c "import sys; raise SystemExit(0 if sys.version_info>=(3,11) else 1)" >nul 2>&1
  if not errorlevel 1 set "PYCMD=py -3" & goto :found
)
where python >nul 2>&1
if not errorlevel 1 (
  python -c "import sys; raise SystemExit(0 if sys.version_info>=(3,11) else 1)" >nul 2>&1
  if not errorlevel 1 set "PYCMD=python" & goto :found
)

echo.
echo 未找到可用的 Python 3.11 或更高版本。
echo 请安装 Python 3.12（推荐）：https://www.python.org/downloads/
echo 安装时勾选 "Add python.exe to PATH"，然后重新双击 open-console.bat。
echo.
echo 也可在 Microsoft Store 或命令行安装： winget install Python.Python.3.12
echo.
start https://www.python.org/downloads/
pause
exit /b 2

:found
echo Starting Universal Browser console... A browser tab opens automatically.
echo Keep this window open while you use the console. Close it to stop.
echo Using: %PYCMD%
%PYCMD% "%INVOKE%" ui %*
if errorlevel 1 (
  echo.
  echo The console stopped with an error. See the message above.
  pause
)
