#!/usr/bin/env bash
# controller.sh - same as run.sh (sets up the venv, then starts the controller).
# Buddies: controller.bat, controller.ps1.   ./controller.sh --list-ports / --port /dev/ttyACM0
exec "$(dirname "$0")/run.sh" "$@"
