@echo off
REM run.bat - ARM's entry point. Sets up .\venv the first time (and again
REM whenever requirements.txt changes), then starts scripts\controller.py.
REM Arguments go to the controller, e.g.  run.bat --mode fleet
setlocal
cd /d "%~dp0"
set "VENV=%~dp0venv"
set "PY=%VENV%\Scripts\python.exe"

if not exist "%PY%" (
    echo Creating venv ...
    py -3 -m venv "%VENV%" 2>nul || python -m venv "%VENV%"
)
if not exist "%PY%" goto :nopython

REM (Re)install only when requirements.txt changed since the last install.
fc /b requirements.txt "%VENV%\requirements.installed" >nul 2>&1
if errorlevel 1 (
    echo Installing requirements - the first time takes a while ...
    "%PY%" -m pip install --upgrade pip
    "%PY%" -m pip install -r requirements.txt || goto :fail
    copy /y requirements.txt "%VENV%\requirements.installed" >nul
)

cd scripts
"%PY%" controller.py %*
if errorlevel 1 pause
exit /b

:nopython
echo Python was not found. Install it from https://www.python.org/downloads/
echo (tick "Add python.exe to PATH"), then run this again.
pause
exit /b 1

:fail
echo Setup failed - see the errors above.
pause
exit /b 1
