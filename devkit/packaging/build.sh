#!/usr/bin/env bash
# Build the zero-install bundle -> dist/dumbtv-devkit/ (zip it for a Release).
set -e
cd "$(dirname "$0")/.."               # devkit/
PY=${PYTHON:-python3}
"$PY" -m pip install -q --upgrade pip
"$PY" -m pip install -q -r requirements.txt pyinstaller
"$PY" -m PyInstaller --noconfirm packaging/dumbtv-devkit.spec
echo "built dist/dumbtv-devkit/  (zip it and attach to a GitHub Release)"
