# cpp_controller.ps1 - runs the C++ controller (build it first: build_cpp_controller.ps1).
# Buddies: cpp_controller.bat, cpp_controller.sh.
$exe = Join-Path $PSScriptRoot "scripts\cpp_controller\build\controller.exe"
if (-not (Test-Path $exe)) { Write-Host "controller.exe not found - build it first with build_cpp_controller.ps1"; exit 1 }
& $exe @args
exit $LASTEXITCODE
