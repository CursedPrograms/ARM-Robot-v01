# go_controller.ps1 - the Go controller. Buddies: go_controller.bat, go_controller.sh.
if (-not (Get-Command go -ErrorAction SilentlyContinue)) { Write-Host "Go was not found. Install it from https://go.dev/dl/"; exit 1 }
if (-not (Get-Command gcc -ErrorAction SilentlyContinue)) {
    Write-Host "The Go controller's window toolkit (Fyne) needs a C compiler on Windows: winget install BrechtSanders.WinLibs.POSIX.UCRT"; exit 1 }
Set-Location (Join-Path $PSScriptRoot "scripts\go_controller")
go run . @args
exit $LASTEXITCODE
