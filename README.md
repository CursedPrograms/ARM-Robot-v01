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

## Fleet Integration

This arm can join the [RIFT](https://github.com/CursedPrograms/RIFT) fleet dashboard, the same way MILA/WHIP/NORA/KIDA do. `controller.py`'s Fleet mode bridges RIFT's HTTP protocol to the Arduino's USB serial connection: it serves `/status`, `/cmd?motor=&angle=`, and `/reset`, and heartbeats a `/register` call to RIFT/NORA so this arm ("ARM", port `5011`) shows up in the dashboard.

```bash
pip install -r requirements.txt
python scripts/controller.py --list-ports              # find the Arduino's port
python scripts/controller.py --port COM6 --mode fleet
```

Per-motor servo channel, angle range, resting angle, and invert flag all come from `config.json` (see `scripts/motor_config.py`) - the same config `slider_controller.py` uses. `.bat` launchers (`controller.bat`, `slider_controller.bat`, `fleet_server.bat`, `run_joystick_test.bat`) live at the repo root alongside `config.json`; the Python scripts themselves stay in `scripts/`.

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
