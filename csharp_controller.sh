#!/usr/bin/env bash
# Linux/macOS launcher for the C# controller (see csharp_controller.bat for Windows).
# Usage: ./csharp_controller.sh --list-ports
#        ./csharp_controller.sh --port /dev/ttyACM0
set -e

if ! command -v dotnet >/dev/null 2>&1; then
    echo "The .NET SDK was not found on this system."
    echo "Install the .NET 8 SDK from https://dotnet.microsoft.com/download"
    exit 1
fi

cd "$(dirname "$0")"
exec dotnet run --project scripts/csharp_controller -c Release -- "$@"
