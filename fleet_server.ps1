# fleet_server.ps1 - the controller in Fleet mode: RIFT bridge + the web page on port 5011.
# Buddies: fleet_server.bat, fleet_server.sh.
& "$PSScriptRoot\run.ps1" --mode fleet @args
exit $LASTEXITCODE
