#!/bin/bash
# fleet_server.sh - the controller in Fleet mode: RIFT bridge + the web page on port 5011.
# Buddies: fleet_server.bat, fleet_server.ps1.
exec "$(dirname "$0")/run.sh" --mode fleet "$@"
