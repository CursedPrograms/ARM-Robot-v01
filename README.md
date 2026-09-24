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

- Robot Type: 6 DOF Arm

---

### Software
- [Arduino IDE](https://docs.arduino.cc/software/ide/)

---

## Related Projects

- [WHIP-Robot-v00](https://github.com/CursedPrograms/WHIP-Robot-v00)
- [KIDA-Robot-v00](https://github.com/CursedPrograms/KIDA-Robot-v00)
- [KIDA-Robot-v01](https://github.com/CursedPrograms/KIDA-Robot-v01)
- [NORA-Robot-v00](https://github.com/CursedPrograms/NORA-Robot-v00)
- [DREAM/ComCentre](https://github.com/CursedPrograms/DREAM)
- [RIFT](https://github.com/CursedPrograms/RIFT)

---

PCA9685 Servo Motor 16 Channel Driver
Arduino Uno

---

## Controls

### Rest pose

| Motor | 1 base | 2 shoulder | 3 elbow | 4 wrist pitch | 5 wrist roll | 6 claw |
|---|---|---|---|---|---|---|
| Rest angle | 135 | 55 | 100 | 230 | 135 | 40 (open) |

The arm goes to this pose:

- **When the Arduino starts up**
- **When no PC is controlling it.** Every controller resends its angles at least every 0.5 s. If `arm.ino` hears nothing for 2 s (controller closed or crashed, cable pulled), the arm eases back to rest.
- **When you let go of the stick.** The stick motors spring back to rest, and the claw opens.
- **When you press Home**, or Reset on the web page

The values live in two places, so change both: `rest` in `config.json` (the controllers) and `REST_ANGLE` in `scripts/arm/arm.ino` (the Arduino, reflash after changing).

### Joystick (Joystick mode)

| Input | Motor | What it does |
|---|---|---|
| Stick left/right (axis 0) | 1 base | Follows the stick, centred = rest |
| Stick forward/back (axis 1) | 2 shoulder | Follows the stick, centred = rest |
| Twist (axis 2) | 5 wrist roll | Follows the stick, centred = rest |
| Hat up / down | 3 elbow | 5° per press |
| Button 3 / button 2 | 4 wrist pitch | 5° per press |
| Trigger (button 0) | 6 claw | Held = closed, released = open |

Holding a hat direction or button counts as one press, and motors 3 and 4 stay where you stepped them when you let go. Every motor stays inside its `min`/`max` from `config.json`, and `invert` flips its direction.

### Keyboard (every mode except IK)

Click the controller window first, since keys only reach the focused window.

| Keys | Motor | Per press |
|---|---|---|
| A / D | 1 base | −5° / +5° |
| W / S | 2 shoulder | up / down 5° |
| R / F | 3 elbow | up / down 5° |
| T / G | 4 wrist pitch | up / down 5° |
| Q / E | 5 wrist roll | −5° / +5° |
| Space | 6 claw | Held = closed, released = open |
| Shift + any key above | | 1° steps for fine positioning |
| Home | all | Back to the `rest` pose |
| 1–9 | | Pick a macro |
| Esc | | Quit |

Holding a key repeats it. Keys write to the same shared angles as everything else, so the sliders, the web page and RIFT follow them. In Joystick mode a key moves a stick motor until you move that stick again.

Keyboard controls are in the Python controller (`controller.py`) only so far.

### Ideas

- Keyboard controls in the C++, C#, Go, Rust and Julia controllers
- Gamepad (Xbox/PlayStation) mapping: two sticks for the arm, triggers for the claw, bumpers for wrist roll
- Pick-and-place challenge: a timer in the window for moving an object from A to B, best run saved as a macro
- Preset macros (wave, bow) on single keys
- Phone tilt control on the web page: tilt to steer the base and shoulder
- Mirror mode: one controller driving two arms through `--connect`

---

## Finding the arm's port

Nothing here needs a hard-coded COM port. `scripts/arm/arm.ino` answers a one-word question, so a controller can find the arm by asking:

```
PC:   WHO
COM6: I am Arm
```

Every controller does this when you leave out `--port`: it opens each port (the compiled controllers only try ports that look like Arduino adapters) at 115200 baud, waits about 2 seconds for the board to reset, sends `WHO`, and uses the port that answers `I am Arm`. If none answers it falls back to the old guess (the first port whose description looks like an Arduino, CH340, CP210x or FTDI adapter). `--port COM6` still overrides all of it, and `--list-ports` lists what's there.

- **You must reflash** the board with the current `arm.ino` before it can answer.
- **Sharing one PC with [DREAM](https://github.com/CursedPrograms/DREAM).** Her sensor board (`dream_sensors.ino`, 9600 baud) answers `WHO` with `I am Dream` the same way, so both projects can run from one computer and each finds its own board, whatever COM numbers Windows hands out. Only one program can hold a serial port, so run one controller per arm.
- **Python:** `scripts/board_id.py` does the asking (`python scripts/board_id.py` lists every port and who answered). **C++, Go, Rust and Julia** ask only the ports that look like Arduino adapters, so they skip Bluetooth ports that can take a long time to open. **C#** can't read USB descriptions, so it asks every port at once.
- Asking a port takes about 3 seconds, so `--port` is faster when you know it.

---

## Colour scheme

Every UI takes its colours from one file, `colour_scheme.xml` in the repo root. Edit a value and restart the controller. The compiled controllers read it at start-up too, so colour changes need no rebuild (build once first to get the code that reads it).

```xml
<colour name="background" value="#33292F"/>
<colour name="button_active" value="#9C0060"/>
```

Write each colour on its own line as `name="..." value="#RRGGBB"` (name first; the C++, Rust and Julia loaders read it line by line). A missing file, or a missing or malformed colour, falls back to the built-in default for that one colour.

| Role | Default | Used for |
|---|---|---|
| `background` | `#33292F` | Window and page background |
| `panel`, `border` | `#331F2B`, `#361529` | Rows, list boxes, outlines |
| `text`, `text_dim` | `#FFFFFF`, `#C9B6C1` | Main text, status lines |
| `button`, `button_hover`, `button_active`, `button_disabled` | `#361529`, `#691548`, `#9C0060`, `#331F2B` | Buttons (active = the selected mode) |
| `accent`, `accent_hover` | `#9C0060`, `#C21F82` | Slider knobs, highlights, values |
| `track`, `selected` | `#691548`, `#691548` | Slider track, the chosen macro |
| `danger`, `danger_hover`, `warn` | `#963232`, `#AD3A3A`, `#F08C3C` | Record and reset, warnings |

How each front end applies it:

| UI | How |
|---|---|
| Python windows (`controller.py`, `slider_controller.py`) | `scripts/colour_scheme.py` supplies the colours |
| Web page | The controller serves `/colour_scheme.xml`; `app.js` applies it over `style.css`'s defaults |
| Julia | Read into the drawing constants at start-up |
| Rust (egui), Go (Fyne) | Applied as the toolkit's theme |
| C# (Avalonia) | Overrides the Fluent theme's button, slider and list colours |
| C++ (Win32) | Window, labels and list box, with owner-drawn buttons. Buttons don't show a hover colour, and slider thumbs keep the Windows look |

The Go, Rust, C# and Julia versions were not built or run when this was added, so the first build is worth a look.

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
- `System.IO.Ports` can't read USB device descriptions like pyserial does, so it asks every port `WHO` at once and uses the one that answers `I am Arm` ([Finding the arm's port](#finding-the-arms-port)). If none answers, it falls back to a simpler guess: on Linux the first `/dev/ttyACM*`/`/dev/ttyUSB*`, on Windows only when there's exactly one COM port. Otherwise pass `--port`.
- Linux permissions: add yourself to the `dialout` group for serial access (`sudo usermod -aG dialout $USER`) and `input` for joystick access, then log out and back in.
- If SDL2 fails to load on Linux, install it from your package manager (e.g. `sudo apt install libsdl2-2.0-0`).

---

## Rust Controller (Windows + Linux)

`scripts/rust_controller/` is a Rust rewrite of `controller.py` for Windows and Linux: same four modes, macros, live sync and `--connect` client mode as the others, in one native executable. The window is [egui](https://github.com/emilk/egui) (via `eframe`), serial is the `serialport` crate (USB descriptions are read, so `--port` auto-detects an Arduino/FTDI/CH340 like the Python version, preferring the port that answers `I am Arm`), and Fleet mode's HTTP server is `tiny_http`. There is no C library to build against: SDL2 is loaded at runtime just for the joystick, so if it isn't found the controller still runs with Joystick mode disabled.

```bat
rust_controller.bat --list-ports
rust_controller.bat --port COM6 --serve
```

```bash
chmod +x rust_controller.sh
./rust_controller.sh --port /dev/ttyACM0 --serve
```

Requires [Rust](https://rustup.rs/) (the first build downloads and compiles the dependencies, which takes a few minutes). Joystick support needs the SDL2 shared library: on Windows put `SDL2.dll` (from the [SDL2 releases](https://github.com/libsdl-org/SDL/releases), `SDL2-2.x.x-win32-x64.zip`) next to the built `arm_controller.exe` or anywhere on `PATH`; on Linux `sudo apt install libsdl2-2.0-0`. Linux serial/joystick permissions are the same as for the C# controller (`dialout` and `input` groups).

---

## Go Controller (Windows + Linux)

`scripts/go_controller/` is a Go rewrite of `controller.py` for Windows and Linux with the same four modes, macros, live sync and `--connect` client mode as the others. The window is [Fyne](https://fyne.io/), serial is `go.bug.st/serial` (USB descriptions are read, so `--port` auto-detects an Arduino/FTDI/CH340, preferring the port that answers `I am Arm`), and Fleet mode's HTTP server is the standard library's `net/http`. SDL2 is loaded at runtime (via [purego](https://github.com/ebitengine/purego), no cgo for that part) just for the joystick, so a missing SDL2 only disables Joystick mode.

```bat
go_controller.bat --list-ports
go_controller.bat --port COM6 --serve
```

```bash
chmod +x go_controller.sh
./go_controller.sh --port /dev/ttyACM0 --serve
```

Requires [Go](https://go.dev/dl/) and, because Fyne uses cgo, a C compiler (Windows: `winget install BrechtSanders.WinLibs.POSIX.UCRT`; Linux: `sudo apt install gcc libgl1-mesa-dev xorg-dev`). The first build downloads and compiles Fyne, which takes a few minutes. Joystick support needs the SDL2 shared library, same as the Rust controller (Windows: `SDL2.dll` next to the executable or on `PATH`; Linux: `sudo apt install libsdl2-2.0-0`).

---

## Fleet Integration

This arm can join the [RIFT](https://github.com/CursedPrograms/RIFT) fleet dashboard, the same way MILA/WHIP/NORA/KIDA do. Both controllers' Fleet mode bridges RIFT's HTTP protocol to the Arduino's USB serial connection: it serves `/status`, `/cmd?motor=&angle=`, and `/reset`, and heartbeats a `/register` call to RIFT/NORA so this arm ("ARM", port `5011`) shows up in the dashboard.

The same HTTP server also serves a small web control page (`scripts/web/index.html`/`style.css`/`app.js`) at `/` - open `http://<this machine's IP>:5011/` in any browser on the network for a per-motor slider UI, no RIFT required.

```bash
pip install -r requirements.txt
python scripts/controller.py --list-ports              # find the Arduino's port
python scripts/controller.py --port COM6 --mode fleet
```

### Live sync between the desktop window and the web page

Whichever controller owns the Arduino's serial port keeps one shared set of motor angles. Its own window (sliders, joystick, IK), the browser page on your phone, and RIFT all read and write that same set, so setting Motor 1 to 140 anywhere shows up everywhere: the desktop sliders move, the web page's sliders move, and the arm moves. The rule is "last writer wins": whichever input changed most recently sets the angle, and inputs you aren't touching just follow it.

Fleet mode starts the HTTP server automatically; add `--serve` to run it in any mode (Sliders, Joystick, IK) so the phone stays in sync while you use the desktop window:

```bash
python scripts/controller.py --port COM6 --serve
cpp_controller.bat --port COM6 --serve
```

The window's status line then shows the address to open on the phone. Only one controller can hold the serial port, so the phone/browser connects to that one; the web page polls four times a second. In Joystick mode an axis only overrides the shared value while you're actually moving it, so untouched axes follow the phone.

### Several controllers on one arm (`--connect`)

Any controller can also run as a client of another one, with no serial port of its own: `--connect http://<hub>:5011` mirrors the hub's angles (10 times a second) and sends this window's changes back, so a Python window on a laptop, the C++ window on the PC and a phone browser all move together. The hub is whichever controller has the Arduino plugged in and `--serve` (or Fleet mode) on. Connecting never moves the arm - the client adopts the hub's angles first - and it works from every controller, including different ones (a C++ client on a Python hub, etc.).

```bash
# PC with the Arduino (the hub)
cpp_controller.bat --port COM6 --serve

# laptop, phone-independent second window
python scripts/controller.py --connect http://192.168.0.10:5011
```

`--connect` can't be combined with `--serve` or `--mode fleet`.

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
