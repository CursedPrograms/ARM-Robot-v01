#!/usr/bin/env bash
# Linux/macOS launcher for the Julia controller (see julia_controller.bat for Windows).
# Usage: ./julia_controller.sh --list-ports
#        ./julia_controller.sh --port /dev/ttyACM0
set -e

if ! command -v julia >/dev/null 2>&1; then
    echo "Julia was not found on this system."
    echo "Install it from https://julialang.org/downloads/ and make sure it is on PATH."
    exit 1
fi

cd "$(dirname "$0")"
PROJECT_DIR="scripts/julia_controller"

if [ ! -f "$PROJECT_DIR/Manifest.toml" ]; then
    echo "First run - installing Julia package dependencies (SDL2, LibSerialPort, HTTP, JSON3 - this can take a few minutes)..."
    julia --project="$PROJECT_DIR" -e 'import Pkg; Pkg.instantiate()'
fi

exec julia --project="$PROJECT_DIR" "$PROJECT_DIR/controller.jl" "$@"
