# run.ps1 - ARM's entry point: sets up venv\ the first time (and again whenever requirements.txt
# changes), then starts scripts\controller.py. Arguments go to the controller (.\run.ps1 --mode fleet).
# Buddies: run.bat, run.sh.
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Creating venv ..."
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv venv } else { python -m venv venv }
}
if (-not (Test-Path $py)) { Write-Host "Python was not found. Install it from https://www.python.org/downloads/"; exit 1 }
$stamp = "venv\requirements.installed"
if (-not (Test-Path $stamp) -or ((Get-FileHash requirements.txt).Hash -ne (Get-FileHash $stamp).Hash)) {
    Write-Host "Installing requirements - the first time takes a while ..."
    & $py -m pip install --upgrade pip
    & $py -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { Write-Host "Setup failed - see the errors above."; exit 1 }
    Copy-Item requirements.txt $stamp -Force
}
Set-Location scripts
& $py controller.py @args
exit $LASTEXITCODE
