# build_cpp_controller.ps1 - builds scripts\cpp_controller\build\controller.exe (g++ from MSYS2 /
# MinGW, else CMake + MSVC). Buddies: build_cpp_controller.bat, build_cpp_controller.sh.
Set-Location (Join-Path $PSScriptRoot "scripts\cpp_controller")
New-Item -ItemType Directory -Force build | Out-Null
if (Test-Path "C:\msys64\ucrt64\bin\g++.exe") { $env:PATH = "C:\msys64\ucrt64\bin;$env:PATH" }   # an old MinGW can't do C++17
if (Get-Command g++ -ErrorAction SilentlyContinue) {
    Write-Host "Building with g++..."
    windres controller.rc -O coff -o build\controller_res.o
    g++ -std=c++17 -O2 -static -o build\controller.exe build\controller_res.o app.cpp motor_config.cpp kinematics.cpp `
        serial_port.cpp joystick.cpp keys_window.cpp macros.cpp fleet_server.cpp remote_arm.cpp colour_scheme.cpp `
        -lws2_32 -lsetupapi -lwinmm -lcomctl32 -lgdi32 -ladvapi32
    if ($LASTEXITCODE -eq 0) { Write-Host "Built - run it with cpp_controller.ps1" } else { Write-Host "Build failed - see errors above."; exit 1 }
} elseif (Get-Command cmake -ErrorAction SilentlyContinue) {
    Write-Host "g++ not found - trying CMake + MSVC instead..."
    cmake -S . -B build
    cmake --build build --config Release
} else {
    Write-Host "No C++ compiler found. Install one: winget install BrechtSanders.WinLibs.POSIX.UCRT (or Visual Studio Build Tools)"
    exit 1
}
