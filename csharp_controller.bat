@echo off
where dotnet >nul 2>nul
if not %errorlevel%==0 (
    echo The .NET SDK was not found on this system.
    echo Install the .NET 8 SDK from https://dotnet.microsoft.com/download
    pause
    exit /b 1
)

cd /d "%~dp0"
dotnet run --project "scripts\csharp_controller" -c Release -- %*
pause
