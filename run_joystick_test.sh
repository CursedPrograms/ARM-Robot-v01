#!/usr/bin/env bash
# Sets up (or reuses) a venv and runs joystick_test.py.
set -e

cd "$(dirname "$0")"

VENV_DIR=".venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtualenv in $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --upgrade pip
    "$VENV_DIR/bin/pip" install -r requirements.txt
fi

exec "$VENV_DIR/bin/python" scripts/joystick_test.py "$@"
