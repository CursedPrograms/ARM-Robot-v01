@echo off
set EXE=%~dp0scripts\cpp_controller\build\controller.exe

if not exist "%EXE%" (
    echo controller.exe not found - build it first by running build_cpp_controller.bat
    pause
    exit /b 1
)

"%EXE%" %*
pause
