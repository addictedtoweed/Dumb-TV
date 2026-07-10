@echo off
REM Launch the dev-kit sim with nothing installed globally: makes a local .venv
REM the first time, installs deps into it, then runs. Passes through app.py args:
REM     run.bat --firmware ..\fw\learn_remote.bin
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo creating local .venv ^(one-time^) ...
    py -3 -m venv .venv || python -m venv .venv
    ".venv\Scripts\python.exe" -m pip install -q --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
)
".venv\Scripts\python.exe" app.py %*
