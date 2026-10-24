# controller.ps1 - same as run.ps1 (sets up the venv, then starts the controller).
# Buddies: controller.bat, controller.sh.
& "$PSScriptRoot\run.ps1" @args
exit $LASTEXITCODE
