# csharp_controller.ps1 - the C# controller. Buddies: csharp_controller.bat, csharp_controller.sh.
Set-Location $PSScriptRoot
if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    Write-Host "The .NET SDK was not found. Install the .NET 8 SDK from https://dotnet.microsoft.com/download"; exit 1 }
dotnet run --project scripts\csharp_controller -c Release -- @args
exit $LASTEXITCODE
