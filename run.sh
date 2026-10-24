#!/bin/bash
# run.sh - ARM's entry point: sets up venv/ the first time (and again whenever requirements.txt
# changes), then starts scripts/controller.py. Arguments go to the controller (./run.sh --mode fleet).
# Buddies: run.bat, run.ps1.
cd "$(dirname "$0")"
if [ ! -x venv/bin/python ]; then
    echo "Creating venv ..."
    python3 -m venv venv || { echo "Python 3 with venv was not found (sudo apt install python3-venv)"; exit 1; }
fi
if ! cmp -s requirements.txt venv/requirements.installed; then
    echo "Installing requirements - the first time takes a while ..."
    venv/bin/python -m pip install --upgrade pip
    venv/bin/python -m pip install -r requirements.txt || { echo "Setup failed - see the errors above."; exit 1; }
    cp requirements.txt venv/requirements.installed
fi
cd scripts
exec ../venv/bin/python controller.py "$@"
