#!/usr/bin/env bash
# Linux/macOS launcher for the Rust controller (see rust_controller.bat for Windows).
# Usage: ./rust_controller.sh --list-ports
#        ./rust_controller.sh --port /dev/ttyACM0
set -e

if ! command -v cargo >/dev/null 2>&1; then
    echo "Rust was not found on this system."
    echo "Install it from https://rustup.rs/ and re-run this script."
    exit 1
fi

cd "$(dirname "$0")"
exec cargo run --release --manifest-path scripts/rust_controller/Cargo.toml -- "$@"
