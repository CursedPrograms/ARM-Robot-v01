#!/usr/bin/env bash
# Linux/macOS launcher for the Python controller (see controller.bat for Windows).
# Usage: ./controller.sh --list-ports
#        ./controller.sh --port /dev/ttyACM0 --serve
set -e

cd "$(dirname "$0")/scripts"

if command -v python3 >/dev/null 2>&1; then
    exec python3 controller.py "$@"
elif command -v python >/dev/null 2>&1; then
    exec python controller.py "$@"
else
    echo "Python was not found on this system. Install Python 3, then: pip install -r requirements.txt"
    exit 1
fi
