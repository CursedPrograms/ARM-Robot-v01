#!/usr/bin/env bash
# Linux/macOS launcher for the Go controller (see go_controller.bat for Windows).
# Usage: ./go_controller.sh --list-ports
#        ./go_controller.sh --port /dev/ttyACM0
set -e

if ! command -v go >/dev/null 2>&1; then
    echo "Go was not found on this system."
    echo "Install it from https://go.dev/dl/ and re-run this script."
    exit 1
fi

cd "$(dirname "$0")/scripts/go_controller"
exec go run . "$@"
