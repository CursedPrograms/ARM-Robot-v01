#!/usr/bin/env python3
"""
controller.py - Main arm control script. Switch at runtime between three
input modes and record/replay motion macros in any of them, talking to the
Arduino running scripts/arm/arm.ino over USB serial.

Modes (click the buttons, or the Joystick/Sliders/IK mode is picked with
--mode at startup):
    Joystick - drive motors 1-6 from a joystick (same mapping as before):
        Axis 0 -> Motor 1 (base), Axis 1 -> Motor 2 (shoulder),
        Hat 0 Y -> Motor 3 (elbow), Buttons 2/3 -> Motor 4 (wrist),
        Axis 2 -> Motor 5 (wrist roll), Button 0 -> Motor 6 (claw)
    Sliders  - drag on-screen sliders to set each motor's raw angle directly.
    IK       - drag X/Y/Z/Pitch/Roll sliders to set a target end-effector
               pose; motors 1-4 are solved with inverse_kinematics() from
               IK_controller.py. Requires config.json's "geometry"
               to be measured first (see IK_controller.py).
    Fleet    - starts an HTTP bridge (same wire protocol as RIFT's
               Fleet/register.py) so the [RIFT](https://github.com/CursedPrograms/RIFT)
               dashboard can see and control this arm over the network, the
               same way it talks to MILA/WHIP/NORA/KIDA: serves /status,
               /cmd?motor=&angle=, and /reset, and heartbeats a /register
               call to RIFT/NORA. Requires pip install flask requests.

Recording: click Record to start capturing every commanded motor pose
(sampled every frame, so IK's continuously-interpolated motion is captured
smoothly, not just as keyframes) in whichever mode is active. Click it
again to stop and save the macro to scripts/macros/. Select a saved macro
(click it, or press 1-9) and click Play to replay it over serial exactly as
recorded, in real time, in any mode - live control resumes automatically
when playback finishes.

Requires:
    pip install pygame pyserial
    pip install flask requests   # only needed for Fleet mode

Usage:
    python controller.py --list-ports          # find your Arduino's port
    python controller.py --port COM6
    python controller.py --port COM6 --mode slider
    python controller.py --port COM6 --mode fleet --fleet-port 5011
"""

import argparse
import json
import sys
import threading
import time
from pathlib import Path

try:
    import pygame
except ImportError:
    print("pygame is not installed. Install it with: pip install pygame")
    sys.exit(1)

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("pyserial is not installed. Install it with: pip install pyserial")
    sys.exit(1)

from motor_config import load_motor_config, load_geometry
from IK_controller import inverse_kinematics
from slider_controller import Slider

MACROS_DIR = Path(__file__).resolve().parent / "macros"

# ---- Joystick wiring (Joystick mode only) ----
AXIS_MOTOR1 = 0
AXIS_MOTOR2 = 1
AXIS_MOTOR5 = 2  # A2 and A3 move together on this stick; only A2 is read
HAT_MOTOR3 = 0
HAT_MOTOR3_COMPONENT = 1
BUTTON_MOTOR4_BACKWARD = 2
BUTTON_MOTOR4_FORWARD = 3
BUTTON_MOTOR6_CLOSE = 0
DEADZONE = 0.05

# Descriptions that identify likely Arduino USB-serial adapters, for --port auto-detect
ARDUINO_HINTS = ("arduino", "ch340", "usb-serial", "usb serial", "cp210", "ftdi")

# ---- Fleet mode (RIFT HTTP bridge) ----
FLEET_NAME = "ARM"
FLEET_TYPE = "robot"
FLEET_CAPABILITIES = ["servo_control", "6dof", "arm"]
DEFAULT_FLEET_PORT = 5011
# Must stay under RIFT's FLEET_TTL_SECS (20s) - same cadence as RIFT's own Fleet/register.py.
FLEET_HEARTBEAT_SECS = 10

# ---- Window layout ----
WINDOW_WIDTH, WINDOW_HEIGHT = 560, 680
MODE_BUTTON_Y = 56
TRANSPORT_BUTTON_Y = 100
MACRO_LIST_Y = 138
MACRO_ROW_H = 16
MACRO_LIST_MAX = 6
MARGIN_TOP = 250
ROW_HEIGHT = 60
# Note: Slider (imported from slider_controller) draws using slider_controller's
# own SLIDER_X/SLIDER_WIDTH/KNOB_RADIUS module constants, not ones defined here.

BG_COLOR = (30, 30, 30)
TEXT_COLOR = (230, 230, 230)
STATUS_COLOR = (150, 150, 150)
WARN_COLOR = (240, 140, 60)
BUTTON_COLOR = (70, 70, 70)
BUTTON_HOVER_COLOR = (100, 100, 100)
BUTTON_ACTIVE_COLOR = (60, 120, 90)
BUTTON_RECORD_COLOR = (150, 50, 50)
MACRO_SELECTED_COLOR = (80, 130, 180)


def axis_to_angle(value, lo, hi, deadzone=DEADZONE):
    """Map a [-1, 1] joystick axis value to [lo, hi] degrees, with deadzone."""
    if abs(value) < deadzone:
        value = 0.0
    angle = (value + 1.0) / 2.0 * (hi - lo) + lo
    return int(round(angle))


def list_joysticks():
    pygame.init()
    pygame.joystick.init()
    count = pygame.joystick.get_count()
    if count == 0:
        print("No joystick/controller devices found.")
        return
    print(f"Found {count} device(s):")
    for i in range(count):
        js = pygame.joystick.Joystick(i)
        js.init()
        print(f"  [{i}] {js.get_name()}  "
              f"(axes={js.get_numaxes()}, buttons={js.get_numbuttons()}, hats={js.get_numhats()})")
        js.quit()


def list_serial_ports():
    ports = list_ports.comports()
    if not ports:
        print("No serial ports found.")
        return
    print("Available serial ports:")
    for p in ports:
        print(f"  {p.device}  -  {p.description}")


def autodetect_port():
    for p in list_ports.comports():
        if any(hint in p.description.lower() for hint in ARDUINO_HINTS):
            return p.device
    return None


def geometry_ready(geometry):
    return geometry.get("upperArmLength", 0) != 0 and geometry.get("forearmLength", 0) != 0


def joystick_commands(js, motors):
    """Read the joystick and return {channel: angle} for all 6 motors."""
    motor1_val = js.get_axis(AXIS_MOTOR1) if js.get_numaxes() > AXIS_MOTOR1 else 0.0
    motor2_val = js.get_axis(AXIS_MOTOR2) if js.get_numaxes() > AXIS_MOTOR2 else 0.0
    motor3_val = js.get_hat(HAT_MOTOR3)[HAT_MOTOR3_COMPONENT] if js.get_numhats() > HAT_MOTOR3 else 0.0
    motor5_val = js.get_axis(AXIS_MOTOR5) if js.get_numaxes() > AXIS_MOTOR5 else 0.0

    motor4_forward = js.get_button(BUTTON_MOTOR4_FORWARD) if js.get_numbuttons() > BUTTON_MOTOR4_FORWARD else 0
    motor4_backward = js.get_button(BUTTON_MOTOR4_BACKWARD) if js.get_numbuttons() > BUTTON_MOTOR4_BACKWARD else 0
    if motor4_forward and not motor4_backward:
        motor4_val = 1.0
    elif motor4_backward and not motor4_forward:
        motor4_val = -1.0
    else:
        motor4_val = 0.0

    motor6_close = js.get_button(BUTTON_MOTOR6_CLOSE) if js.get_numbuttons() > BUTTON_MOTOR6_CLOSE else 0
    if motors[6]["invert"]:
        motor6_close = not motor6_close
    motor6_angle = motors[6]["max"] if motor6_close else motors[6]["min"]

    if motors[1]["invert"]:
        motor1_val = -motor1_val
    if motors[2]["invert"]:
        motor2_val = -motor2_val
    if motors[3]["invert"]:
        motor3_val = -motor3_val
    if motors[4]["invert"]:
        motor4_val = -motor4_val
    if motors[5]["invert"]:
        motor5_val = -motor5_val

    return {
        motors[1]["channel"]: axis_to_angle(motor1_val, motors[1]["min"], motors[1]["max"]),
        motors[2]["channel"]: axis_to_angle(motor2_val, motors[2]["min"], motors[2]["max"]),
        motors[3]["channel"]: axis_to_angle(motor3_val, motors[3]["min"], motors[3]["max"]),
        motors[4]["channel"]: axis_to_angle(motor4_val, motors[4]["min"], motors[4]["max"]),
        motors[5]["channel"]: axis_to_angle(motor5_val, motors[5]["min"], motors[5]["max"]),
        motors[6]["channel"]: motor6_angle,
    }


def list_macros():
    if not MACROS_DIR.exists():
        return []
    return sorted(MACROS_DIR.glob("*.json"), key=lambda p: p.name, reverse=True)


def save_macro(steps):
    MACROS_DIR.mkdir(exist_ok=True)
    path = MACROS_DIR / f"macro_{time.strftime('%Y%m%d_%H%M%S')}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"created": time.strftime("%Y-%m-%d %H:%M:%S"), "steps": steps}, f)
    return path


def load_macro(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f).get("steps", [])


class Button:
    def __init__(self, rect, label):
        self.rect = pygame.Rect(rect)
        self.label = label

    def hit(self, pos):
        return self.rect.collidepoint(pos)

    def draw(self, surface, font, active=False, color=None):
        bg = color if color else (BUTTON_ACTIVE_COLOR if active else
                                   (BUTTON_HOVER_COLOR if self.rect.collidepoint(pygame.mouse.get_pos()) else BUTTON_COLOR))
        pygame.draw.rect(surface, bg, self.rect, border_radius=6)
        text = font.render(self.label, True, TEXT_COLOR)
        surface.blit(text, text.get_rect(center=self.rect.center))


def start_fleet_heartbeat(rift_host, rift_port, interval=FLEET_HEARTBEAT_SECS):
    """Background thread that repeatedly POSTs /register to RIFT/NORA. Safe to
    call even if the target isn't reachable yet - it just keeps retrying."""
    import requests

    stop_event = threading.Event()

    def _loop():
        while not stop_event.is_set():
            try:
                requests.post(
                    f"http://{rift_host}:{rift_port}/register",
                    data={
                        "name": FLEET_NAME,
                        "type": FLEET_TYPE,
                        "capabilities": ",".join(FLEET_CAPABILITIES),
                    },
                    timeout=2,
                )
            except requests.RequestException:
                pass
            stop_event.wait(interval)

    t = threading.Thread(target=_loop, daemon=True, name="rift-fleet-heartbeat")
    t.start()
    return t, stop_event


def create_fleet_app(motors, fleet_state, fleet_lock, connected):
    """Flask app bridging RIFT's HTTP protocol to fleet_state["angles"], which
    the main loop reads each frame and sends over serial like any other mode."""
    from flask import Flask, jsonify, request

    app = Flask(__name__)

    @app.route("/ping")
    def ping():
        return f"{FLEET_NAME} alive", 200, {"Content-Type": "text/plain"}

    @app.route("/status")
    def status():
        with fleet_lock:
            angles = dict(fleet_state["angles"])
        return jsonify({
            "connected": connected(),
            "motors": {
                str(n): {"channel": m["channel"], "angle": angles[n], "min": m["min"], "max": m["max"]}
                for n, m in motors.items()
            },
        })

    @app.route("/cmd")
    def cmd():
        try:
            motor = int(request.args["motor"])
            angle = int(request.args["angle"])
        except (KeyError, ValueError):
            return jsonify({"error": "expected ?motor=<1-6>&angle=<degrees>"}), 400
        if motor not in motors:
            return jsonify({"error": f"unknown motor {motor}"}), 400
        m = motors[motor]
        angle = max(m["min"], min(m["max"], angle))
        with fleet_lock:
            fleet_state["angles"][motor] = angle
        return jsonify({"motor": motor, "angle": angle})

    @app.route("/reset")
    def reset():
        motor = request.args.get("motor", type=int)
        with fleet_lock:
            if motor is not None:
                if motor not in motors:
                    return jsonify({"error": f"unknown motor {motor}"}), 400
                fleet_state["angles"][motor] = motors[motor]["rest"]
                return jsonify({"motor": motor, "angle": fleet_state["angles"][motor]})
            for n in motors:
                fleet_state["angles"][n] = motors[n]["rest"]
            return jsonify(dict(fleet_state["angles"]))

    return app


def start_fleet_server(args, motors, fleet_state, fleet_lock, connected, fleet_status):
    """Lazily start the Fleet-mode HTTP bridge + RIFT heartbeat, once. Missing
    flask/requests is reported into fleet_status["error"] instead of crashing
    the whole controller, since Fleet mode is optional."""
    if fleet_status["started"] or fleet_status["error"]:
        return

    try:
        app = create_fleet_app(motors, fleet_state, fleet_lock, connected)
    except ImportError:
        fleet_status["error"] = "flask is not installed. Install it with: pip install flask requests"
        return

    def _serve():
        app.run(host="0.0.0.0", port=args.fleet_port, use_reloader=False)

    threading.Thread(target=_serve, daemon=True, name="fleet-http-server").start()
    fleet_status["started"] = True

    if not args.no_register:
        try:
            start_fleet_heartbeat(args.rift_host, args.rift_port)
        except ImportError:
            fleet_status["error"] = "requests is not installed (HTTP server running, but no RIFT heartbeat). Install it with: pip install requests"


def send(ser, commands, last_sent):
    """Send commands (channel:angle) over serial if changed from last_sent. Returns the new last_sent."""
    if commands != last_sent:
        if ser is not None:
            line = ",".join(f"{ch}:{ang}" for ch, ang in commands.items())
            ser.write((line + "\n").encode("ascii"))
        return dict(commands)
    return last_sent


def main():
    parser = argparse.ArgumentParser(description="Unified joystick/slider/IK arm controller with macro recording, over USB serial.")
    parser.add_argument("--device", type=int, default=0, help="Joystick index to use (default 0)")
    parser.add_argument("--port", type=str, default=None, help="Serial port, e.g. COM6 (auto-detected if omitted)")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baud rate (default 115200, must match .ino)")
    parser.add_argument("--rate", type=float, default=30, help="Update rate in Hz (default 30)")
    parser.add_argument("--mode", choices=["joystick", "slider", "ik", "fleet"], default=None, help="Initial mode (default: joystick if one is found, else sliders)")
    parser.add_argument("--list", action="store_true", help="List joystick devices and exit")
    parser.add_argument("--list-ports", action="store_true", help="List serial ports and exit")
    parser.add_argument("--fleet-port", type=int, default=DEFAULT_FLEET_PORT, help=f"Fleet mode HTTP port (default {DEFAULT_FLEET_PORT})")
    parser.add_argument("--rift-host", type=str, default="127.0.0.1", help="Fleet mode: RIFT/NORA fleet-registry host (default 127.0.0.1)")
    parser.add_argument("--rift-port", type=int, default=5000, help="Fleet mode: RIFT/NORA fleet-registry port (default 5000)")
    parser.add_argument("--no-register", action="store_true", help="Fleet mode: don't heartbeat to the fleet registry, just serve the HTTP API")
    args = parser.parse_args()

    if args.list:
        list_joysticks()
        return
    if args.list_ports:
        list_serial_ports()
        return

    motors = load_motor_config()
    geometry = load_geometry()

    pygame.init()
    pygame.joystick.init()
    js = None
    if pygame.joystick.get_count() > args.device:
        js = pygame.joystick.Joystick(args.device)
        js.init()
        print(f"Using joystick: {js.get_name()}")
    else:
        print("No joystick found - Joystick mode will be unavailable.")

    port = args.port or autodetect_port()
    ser = None
    if port:
        try:
            ser = serial.Serial(port, args.baud, timeout=1)
            time.sleep(2)  # give the Arduino time to reset after the serial connection opens
            status = f"Connected to {port} @ {args.baud} baud."
        except serial.SerialException as e:
            status = f"Could not open {port}: {e}"
    else:
        status = "No Arduino-like serial port found - display-only mode."
    print(status)

    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("Arm Controller")
    font = pygame.font.SysFont(None, 24)
    small_font = pygame.font.SysFont(None, 18)
    clock = pygame.time.Clock()

    mode = args.mode or ("joystick" if js else "slider")

    slider_mode_sliders = [
        Slider(f"Motor {n}", motors[n]["channel"], motors[n]["min"], motors[n]["max"], motors[n]["rest"],
               MARGIN_TOP + i * ROW_HEIGHT)
        for i, n in enumerate(sorted(motors))
    ]

    reach = geometry["upperArmLength"] + geometry["forearmLength"] + geometry["wristLength"]
    reach = reach if reach > 0 else 300
    ik_sliders = {
        "x": Slider("Target X (mm)", None, -reach, reach, 0, MARGIN_TOP + 0 * ROW_HEIGHT),
        "y": Slider("Target Y (mm)", None, -reach, reach, 0, MARGIN_TOP + 1 * ROW_HEIGHT),
        "z": Slider("Target Z (mm)", None, 0, reach, geometry["baseHeight"], MARGIN_TOP + 2 * ROW_HEIGHT),
        "pitch": Slider("Pitch (deg)", None, -90, 90, 0, MARGIN_TOP + 3 * ROW_HEIGHT),
        "roll": Slider("Roll (motor 5)", motors[5]["channel"], motors[5]["min"], motors[5]["max"], motors[5]["rest"],
                        MARGIN_TOP + 4 * ROW_HEIGHT),
    }
    elbow_down = False
    claw_closed = False
    ik_reachable = True

    fleet_lock = threading.Lock()
    fleet_state = {"angles": {n: motors[n]["rest"] for n in motors}}
    fleet_status = {"started": False, "error": None}

    def ensure_fleet_started():
        start_fleet_server(args, motors, fleet_state, fleet_lock, lambda: ser is not None, fleet_status)

    if mode == "fleet":
        ensure_fleet_started()

    mode_buttons = {
        "joystick": Button((20, MODE_BUTTON_Y, 122, 34), "Joystick"),
        "slider": Button((152, MODE_BUTTON_Y, 122, 34), "Sliders"),
        "ik": Button((284, MODE_BUTTON_Y, 122, 34), "IK"),
        "fleet": Button((416, MODE_BUTTON_Y, 122, 34), "Fleet"),
    }
    record_button = Button((30, TRANSPORT_BUTTON_Y, 160, 30), "Record")
    play_button = Button((200, TRANSPORT_BUTTON_Y, 160, 30), "Play")
    elbow_toggle = Button((30, MARGIN_TOP + 5 * ROW_HEIGHT, 150, 30), "Elbow: Up")
    claw_toggle = Button((200, MARGIN_TOP + 5 * ROW_HEIGHT, 150, 30), "Claw: Open")

    macros = list_macros()
    selected_macro_index = 0 if macros else None

    recording = False
    record_steps = []
    record_start = 0.0

    playing = False
    play_steps = []
    play_start = 0.0
    play_index = 0
    play_prev_mode = mode

    last_sent = {}
    last_valid_ik_commands = None

    def macro_row_rect(i):
        return pygame.Rect(30, MACRO_LIST_Y + i * MACRO_ROW_H, 500, MACRO_ROW_H)

    running = True
    try:
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running = False
                elif event.type == pygame.KEYDOWN and pygame.K_1 <= event.key <= pygame.K_9 and not playing:
                    idx = event.key - pygame.K_1
                    if idx < len(macros):
                        selected_macro_index = idx
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    pos = event.pos
                    if playing:
                        if play_button.hit(pos):
                            playing = False
                            mode = play_prev_mode
                    else:
                        if mode_buttons["joystick"].hit(pos) and js is not None:
                            mode = "joystick"
                        elif mode_buttons["slider"].hit(pos):
                            mode = "slider"
                        elif mode_buttons["ik"].hit(pos):
                            mode = "ik"
                        elif mode_buttons["fleet"].hit(pos):
                            mode = "fleet"
                            ensure_fleet_started()
                        elif record_button.hit(pos):
                            if not recording:
                                recording = True
                                record_steps = []
                                record_start = time.time()
                            else:
                                recording = False
                                if record_steps:
                                    path = save_macro(record_steps)
                                    print(f"Saved macro: {path.name} ({len(record_steps)} steps)")
                                    macros = list_macros()
                                    selected_macro_index = 0
                        elif play_button.hit(pos) and macros and selected_macro_index is not None:
                            playing = True
                            play_steps = load_macro(macros[selected_macro_index])
                            play_start = time.time()
                            play_index = 0
                            play_prev_mode = mode
                        elif mode == "ik" and elbow_toggle.hit(pos):
                            elbow_down = not elbow_down
                        elif mode == "ik" and claw_toggle.hit(pos):
                            claw_closed = not claw_closed
                        else:
                            for i in range(min(len(macros), MACRO_LIST_MAX)):
                                if macro_row_rect(i).collidepoint(pos):
                                    selected_macro_index = i

                if not playing:
                    if mode == "slider":
                        for s in slider_mode_sliders:
                            s.handle_event(event)
                    elif mode == "ik":
                        for s in ik_sliders.values():
                            s.handle_event(event)

            # ---- compute + send this frame's commands ----
            if playing:
                elapsed = time.time() - play_start
                while play_index < len(play_steps) and play_steps[play_index]["t"] <= elapsed:
                    commands = {int(ch): ang for ch, ang in play_steps[play_index]["commands"].items()}
                    last_sent = send(ser, commands, last_sent)
                    play_index += 1
                if play_index >= len(play_steps):
                    playing = False
                    mode = play_prev_mode
            else:
                commands = None
                if mode == "joystick" and js is not None:
                    commands = joystick_commands(js, motors)
                elif mode == "slider":
                    commands = {s.channel: s.angle for s in slider_mode_sliders}
                elif mode == "ik":
                    if geometry_ready(geometry):
                        sol = inverse_kinematics(
                            motors, geometry,
                            ik_sliders["x"].angle, ik_sliders["y"].angle, ik_sliders["z"].angle,
                            pitch_deg=ik_sliders["pitch"].angle, elbow_down=elbow_down,
                        )
                        if sol is not None:
                            ik_reachable = True
                            commands = {motors[n]["channel"]: a for n, a in sol.items()}
                            commands[motors[5]["channel"]] = ik_sliders["roll"].angle
                            commands[motors[6]["channel"]] = motors[6]["max"] if claw_closed else motors[6]["min"]
                            last_valid_ik_commands = commands
                        else:
                            ik_reachable = False
                            commands = last_valid_ik_commands  # hold last good pose
                elif mode == "fleet":
                    with fleet_lock:
                        commands = {motors[n]["channel"]: fleet_state["angles"][n] for n in motors}

                if commands is not None:
                    last_sent = send(ser, commands, last_sent)
                    if recording:
                        record_steps.append({
                            "t": time.time() - record_start,
                            "commands": {str(ch): ang for ch, ang in commands.items()},
                        })

            # ---- draw ----
            screen.fill(BG_COLOR)
            screen.blit(font.render("Arm Controller", True, TEXT_COLOR), (20, 16))
            screen.blit(small_font.render(status, True, STATUS_COLOR), (20, 40))

            for name, btn in mode_buttons.items():
                enabled = name != "joystick" or js is not None
                btn.draw(screen, font, active=(mode == name), color=(None if enabled else (50, 50, 50)))

            record_button.label = f"Recording... {time.time() - record_start:.1f}s" if recording else "Record"
            record_button.draw(screen, font, color=(BUTTON_RECORD_COLOR if recording else None))
            play_button.label = "Stop" if playing else "Play"
            play_button.draw(screen, font, active=playing)

            for i, path in enumerate(macros[:MACRO_LIST_MAX]):
                row = macro_row_rect(i)
                if i == selected_macro_index:
                    pygame.draw.rect(screen, MACRO_SELECTED_COLOR, row, border_radius=3)
                screen.blit(small_font.render(f"{i + 1}. {path.stem}", True, TEXT_COLOR), (row.x + 4, row.y))
            if not macros:
                screen.blit(small_font.render("No macros recorded yet.", True, STATUS_COLOR), (30, MACRO_LIST_Y))

            if mode == "slider":
                for s in slider_mode_sliders:
                    s.draw(screen, font)
            elif mode == "ik":
                if not geometry_ready(geometry):
                    screen.blit(small_font.render(
                        "Geometry not measured - fill in config.json's \"geometry\" section.",
                        True, WARN_COLOR), (20, MARGIN_TOP - 20))
                else:
                    for s in ik_sliders.values():
                        s.draw(screen, font)
                    if not ik_reachable:
                        screen.blit(small_font.render("Target unreachable - holding last valid pose.", True, WARN_COLOR),
                                    (20, MARGIN_TOP + 5 * ROW_HEIGHT - 18))
                    elbow_toggle.label = f"Elbow: {'Down' if elbow_down else 'Up'}"
                    elbow_toggle.draw(screen, small_font)
                    claw_toggle.label = f"Claw: {'Closed' if claw_closed else 'Open'}"
                    claw_toggle.draw(screen, small_font)
            elif mode == "joystick":
                if js is None:
                    screen.blit(small_font.render("No joystick connected.", True, WARN_COLOR), (20, MARGIN_TOP - 20))
                elif last_sent:
                    channel_to_motor = {m["channel"]: n for n, m in motors.items()}
                    y = MARGIN_TOP
                    for ch, ang in sorted(last_sent.items()):
                        n = channel_to_motor.get(ch, "?")
                        screen.blit(font.render(f"Motor {n} (ch {ch}): {ang}", True, TEXT_COLOR), (20, y))
                        y += 28
            elif mode == "fleet":
                if fleet_status["error"]:
                    screen.blit(small_font.render(fleet_status["error"], True, WARN_COLOR), (20, MARGIN_TOP - 20))
                else:
                    screen.blit(small_font.render(
                        f"Serving http://0.0.0.0:{args.fleet_port}  (/status, /cmd?motor=&angle=, /reset)"
                        + ("" if args.no_register else f"  -  heartbeating to RIFT at {args.rift_host}:{args.rift_port}"),
                        True, STATUS_COLOR), (20, MARGIN_TOP - 20))
                    y = MARGIN_TOP
                    for n, m in sorted(motors.items()):
                        with fleet_lock:
                            ang = fleet_state["angles"][n]
                        screen.blit(font.render(f"Motor {n} (ch {m['channel']}): {ang}", True, TEXT_COLOR), (20, y))
                        y += 28

            if playing:
                screen.blit(small_font.render(f"Playing... step {play_index}/{len(play_steps)}", True, STATUS_COLOR),
                            (370, TRANSPORT_BUTTON_Y + 8))

            pygame.display.flip()
            clock.tick(args.rate if args.rate > 0 else 30)
    finally:
        if ser is not None:
            ser.close()
        if js is not None:
            js.quit()
        pygame.joystick.quit()
        pygame.quit()


if __name__ == "__main__":
    main()
