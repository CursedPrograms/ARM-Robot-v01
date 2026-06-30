@echo off
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py run.py %*
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        python run.py %*
    ) else (
        echo Python was not found on this system.
        echo Install it from https://www.python.org/downloads/ and make sure
        echo "Add python.exe to PATH" is checked during install.
        echo.
        echo If you already installed Python and still see this, go to:
        echo Settings ^> Apps ^> Advanced app settings ^> App execution aliases
        echo and turn OFF "python.exe" / "python3.exe".
    )
)

pause
