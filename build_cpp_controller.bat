@echo off
cd /d "%~dp0scripts\cpp_controller"

if not exist build mkdir build

where g++ >nul 2>nul
if %errorlevel%==0 (
    echo Building with g++...
    g++ -std=c++17 -O2 -o build\controller.exe app.cpp motor_config.cpp kinematics.cpp serial_port.cpp joystick.cpp macros.cpp fleet_server.cpp remote_arm.cpp -lws2_32 -lsetupapi -lwinmm -lcomctl32
    if %errorlevel%==0 (
        echo.
        echo Built scripts\cpp_controller\build\controller.exe - run it with cpp_controller.bat
    ) else (
        echo.
        echo Build failed - see errors above.
    )
) else (
    where cmake >nul 2>nul
    if %errorlevel%==0 (
        echo g++ not found on PATH - trying CMake + MSVC instead...
        cmake -S . -B build
        cmake --build build --config Release
        echo.
        echo If that succeeded, look for controller.exe under scripts\cpp_controller\build\
    ) else (
        echo No C++ compiler found.
        echo.
        echo Install a compiler, then re-run this script. Either works:
        echo   - MinGW-w64:            winget install BrechtSanders.WinLibs.POSIX.UCRT
        echo   - Visual Studio Build Tools ^(includes CMake support^)
    )
)

pause
