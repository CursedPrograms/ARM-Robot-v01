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

## Fleet Integration

This arm can join the [RIFT](https://github.com/CursedPrograms/RIFT) fleet dashboard, the same way MILA/WHIP/NORA/KIDA do. Both controllers' Fleet mode bridges RIFT's HTTP protocol to the Arduino's USB serial connection: it serves `/status`, `/cmd?motor=&angle=`, and `/reset`, and heartbeats a `/register` call to RIFT/NORA so this arm ("ARM", port `5011`) shows up in the dashboard.

The same HTTP server also serves a small web control page (`scripts/web/index.html`/`style.css`/`app.js`) at `/` - open `http://<this machine's IP>:5011/` in any browser on the network for a per-motor slider UI, no RIFT required.

```bash
pip install -r requirements.txt
python scripts/controller.py --list-ports              # find the Arduino's port
python scripts/controller.py --port COM6 --mode fleet
```

Per-motor servo channel, angle range, resting angle, and invert flag all come from `config.json` (see `scripts/motor_config.py`) - the same config `slider_controller.py` uses. `.bat` launchers (`controller.bat`, `slider_controller.bat`, `fleet_server.bat`, `run_joystick_test.bat`, `build_cpp_controller.bat`, `cpp_controller.bat`) live at the repo root alongside `config.json`; the Python and C++ sources themselves stay under `scripts/`.

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
