@echo off
where go >nul 2>nul
if not %errorlevel%==0 (
    echo Go was not found on this system.
    echo Install it from https://go.dev/dl/ and re-run this script.
    pause
    exit /b 1
)

where gcc >nul 2>nul
if not %errorlevel%==0 (
    echo The Go controller's window toolkit ^(Fyne^) needs a C compiler on Windows.
    echo Install MinGW-w64: winget install BrechtSanders.WinLibs.POSIX.UCRT
    pause
    exit /b 1
)

cd /d "%~dp0scripts\go_controller"
go run . %*
pause
