#!/usr/bin/env bash
# Launch the dev-kit sim with nothing installed globally: this makes a local
# .venv the first time, installs the deps into it, then runs. Pass through any
# app.py args, e.g.:  ./run.sh --firmware ../fw/learn_remote.bin
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}

if [ ! -x .venv/bin/python ]; then
    echo "creating local .venv (one-time) ..."
    "$PY" -m venv .venv
    .venv/bin/python -m pip install -q --upgrade pip
    .venv/bin/python -m pip install -q -r requirements.txt
fi
exec .venv/bin/python app.py "$@"
