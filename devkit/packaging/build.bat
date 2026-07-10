@echo off
REM Build the zero-install bundle -> dist\dumbtv-devkit\ (zip it for a Release).
setlocal
cd /d "%~dp0\.."
py -3 -m pip install -q --upgrade pip
py -3 -m pip install -q -r requirements.txt pyinstaller
py -3 -m PyInstaller --noconfirm packaging\dumbtv-devkit.spec
echo built dist\dumbtv-devkit\  (zip it and attach to a GitHub Release)
