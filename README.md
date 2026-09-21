[![Twitter: @NorowaretaGemu](https://img.shields.io/badge/X-@NorowaretaGemu-blue.svg?style=flat)](https://x.com/NorowaretaGemu)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

<div align="center">
  <a href="https://ko-fi.com/cursedentertainment">
    <img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="ko-fi" style="width: 20%;"/>
  </a>
</div>
<div align="center">
  <img alt="Python" src="https://img.shields.io/badge/python%20-%23323330.svg?&style=for-the-badge&logo=python&logoColor=white"/>
    <img alt="C++" src="https://img.shields.io/badge/c++%20-%23323330.svg?&style=for-the-badge&logo=c%2B%2B&logoColor=white"/>
    <img alt="Julia" src="https://img.shields.io/badge/julia%20-%23323330.svg?&style=for-the-badge&logo=julia&logoColor=white"/>
    <img alt="C#" src="https://img.shields.io/badge/c%23%20-%23323330.svg?&style=for-the-badge&logo=csharp&logoColor=white"/>
</div>

---

# ARM-Robot-v01

## Related Projects

- [WHIP-Robot-v00](https://github.com/CursedPrograms/WHIP-Robot-v00)
- [KIDA-Robot-v00](https://github.com/CursedPrograms/KIDA-Robot-v00)
- [KIDA-Robot-v01](https://github.com/CursedPrograms/KIDA-Robot-v01)
- [NORA-Robot-v00](https://github.com/CursedPrograms/NORA-Robot-v00)
- [DREAM/ComCentre](https://github.com/CursedPrograms/DREAM)
- [RIFT](https://github.com/CursedPrograms/RIFT)

---

## C++ Controller

`scripts/cpp_controller/` is a native Win32 rewrite of `controller.py` with the same four modes (Joystick/Sliders/IK/Fleet) and the same macro recording/playback, for anyone who'd rather run a standalone `.exe` than install Python/pygame. It reads the same `config.json`, records to the same `scripts/macros/*.json`, and its Fleet mode serves the same `scripts/web/` control page and HTTP API - the two controllers are drop-in equivalents of each other.

```bat
build_cpp_controller.bat
cpp_controller.bat --list-ports
cpp_controller.bat --port COM6 --mode fleet
```

`build_cpp_controller.bat` compiles it with `g++` (MinGW-w64) if found on `PATH`, falling back to CMake + MSVC otherwise, producing `scripts/cpp_controller/build/controller.exe`. It only depends on the Windows SDK (Win32, Winsock, winmm, SetupAPI) - no other libraries to install.

---

## Julia Controller

`scripts/julia_controller/` is a Julia rewrite of `controller.py`, for anyone who'd rather use Julia than Python or C++. Same four modes (Joystick/Sliders/IK/Fleet), same macro recording/playback, same `config.json`/`scripts/macros/*.json`/`scripts/web/` - a drop-in equivalent of the other two controllers. It draws its window with SDL2 (via [SimpleDirectMediaLayer.jl](https://github.com/JuliaMultimedia/SimpleDirectMediaLayer.jl), the same library pygame itself is built on) and talks to the Arduino over [LibSerialPort.jl](https://github.com/JuliaIO/LibSerialPort.jl); Fleet mode's HTTP bridge is [HTTP.jl](https://github.com/JuliaWeb/HTTP.jl).

```bat
julia_controller.bat --list-ports
julia_controller.bat --port COM6
julia_controller.bat --port COM6 --mode fleet
```

`julia_controller.bat` installs the Julia package dependencies on first run (`Pkg.instantiate()`, using `scripts/julia_controller/Project.toml`) and then launches `controller.jl` - no separate build step, same as the Python controller. Requires [Julia](https://julialang.org/downloads/) on `PATH`.

---

## C# Controller (Windows + Linux)

`scripts/csharp_controller/` is a C# / .NET 8 rewrite of `controller.py` that runs on both Windows and Linux. Same four modes (Joystick/Sliders/IK/Fleet), same macro recording/playback, same `config.json`/`scripts/macros/*.json`/`scripts/web/` as the other controllers. The window is [Avalonia](https://avaloniaui.net/) (cross-platform, built in code rather than XAML), joystick input goes through SDL2 via [Silk.NET.SDL](https://github.com/dotnet/Silk.NET) (which bundles the native SDL2 library), serial is `System.IO.Ports`, and Fleet mode's HTTP bridge is Kestrel (ASP.NET Core), so it binds to the network without needing admin rights.

```bat
csharp_controller.bat --list-ports
csharp_controller.bat --port COM6
csharp_controller.bat --port COM6 --mode fleet
```

```bash
chmod +x csharp_controller.sh
./csharp_controller.sh --list-ports
./csharp_controller.sh --port /dev/ttyACM0
```

Requires the [.NET 8 SDK](https://dotnet.microsoft.com/download); the launchers run it with `dotnet run`, which restores NuGet packages on first run.

Notes:
- `System.IO.Ports` can't read USB device descriptions like pyserial does, so port auto-detect is simpler: on Linux it picks the first `/dev/ttyACM*`/`/dev/ttyUSB*`, on Windows it only auto-picks if there's exactly one COM port. Otherwise pass `--port`.
- Linux permissions: add yourself to the `dialout` group for serial access (`sudo usermod -aG dialout $USER`) and `input` for joystick access, then log out and back in.
- If SDL2 fails to load on Linux, install it from your package manager (e.g. `sudo apt install libsdl2-2.0-0`).

---

## Fleet Integration

This arm can join the [RIFT](https://github.com/CursedPrograms/RIFT) fleet dashboard, the same way MILA/WHIP/NORA/KIDA do. Both controllers' Fleet mode bridges RIFT's HTTP protocol to the Arduino's USB serial connection: it serves `/status`, `/cmd?motor=&angle=`, and `/reset`, and heartbeats a `/register` call to RIFT/NORA so this arm ("ARM", port `5011`) shows up in the dashboard.

The same HTTP server also serves a small web control page (`scripts/web/index.html`/`style.css`/`app.js`) at `/` - open `http://<this machine's IP>:5011/` in any browser on the network for a per-motor slider UI, no RIFT required.

```bash
pip install -r requirements.txt
python scripts/controller.py --list-ports              # find the Arduino's port
python scripts/controller.py --port COM6 --mode fleet
```

Per-motor servo channel, angle range, resting angle, and invert flag all come from `config.json` (see `scripts/motor_config.py`) - the same config `slider_controller.py` uses. `.bat` launchers (`controller.bat`, `slider_controller.bat`, `fleet_server.bat`, `run_joystick_test.bat`, `build_cpp_controller.bat`, `cpp_controller.bat`, `julia_controller.bat`, `csharp_controller.bat`/`.sh`) live at the repo root alongside `config.json`; the Python, C++, Julia, and C# sources themselves stay under `scripts/`.

---

<br>
<div align="center">
© Cursed Entertainment 2026
</div>
<br>
<div align="center">
<a href="https://cursed-entertainment.itch.io/" target="_blank">
    <img src="https://github.com/CursedPrograms/cursedentertainment/raw/main/images/logos/logo-wide-grey.png"
        alt="CursedEntertainment Logo" style="width:250px;">
</a>
</div>
