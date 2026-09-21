@echo off
where julia >nul 2>nul
if not %errorlevel%==0 (
    echo Julia was not found on this system.
    echo Install it from https://julialang.org/downloads/ and make sure
    echo "Add Julia to PATH" is checked during install.
    pause
    exit /b 1
)

set PROJECT_DIR=%~dp0scripts\julia_controller

if not exist "%PROJECT_DIR%\Manifest.toml" (
    echo First run - installing Julia package dependencies ^(SDL2, LibSerialPort, HTTP, JSON3 - this can take a few minutes^)...
    julia --project="%PROJECT_DIR%" -e "import Pkg; Pkg.instantiate()"
    if not %errorlevel%==0 (
        echo.
        echo Dependency install failed - see errors above.
        pause
        exit /b 1
    )
)

julia --project="%PROJECT_DIR%" "%PROJECT_DIR%\controller.jl" %*
pause
