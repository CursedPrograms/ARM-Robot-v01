# julia_controller.ps1 - the Julia controller (installs its packages on the first run).
# Buddies: julia_controller.bat, julia_controller.sh.
if (-not (Get-Command julia -ErrorAction SilentlyContinue)) {
    Write-Host "Julia was not found. Install it from https://julialang.org/downloads/ (tick Add Julia to PATH)"; exit 1 }
$proj = Join-Path $PSScriptRoot "scripts\julia_controller"
if (-not (Test-Path (Join-Path $proj "Manifest.toml"))) {
    Write-Host "First run - installing Julia packages (SDL2, LibSerialPort, HTTP, JSON3): a few minutes..."
    julia --project="$proj" -e "import Pkg; Pkg.instantiate()"
    if ($LASTEXITCODE -ne 0) { Write-Host "Dependency install failed - see errors above."; exit 1 }
}
julia --project="$proj" (Join-Path $proj "controller.jl") @args
exit $LASTEXITCODE
