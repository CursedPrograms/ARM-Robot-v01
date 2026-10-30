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
        Axis 2 -> Motor 5 (wrist roll), Button 0 (trigger) -> Motor 6 (claw)
        The hat and buttons 2/3 move their motor BUTTON_STEP_DEG (5) degrees per
        press. The "Hold position" tick box picks what the stick does: ticked, it
        sets speed, letting go holds her where she is and the trigger clicks the
        claw shut/open; unticked, it sets position, letting go sends her back to
        rest one joint at a time (nearest the claw first) and the claw is closed
        while the trigger's held. No joint ever jumps (StickDriver).
    Keyboard - works in every mode except IK (see README "Controls"):
        A/D base, W/S shoulder, R/F elbow, T/G wrist pitch, Q/E wrist roll:
        5 degrees per press (hold to repeat, Shift for 1 degree).
        Space held = claw closed. Home = back to the rest pose.
    Sliders  - drag on-screen sliders to set each motor's raw angle directly.
    IK       - drag X/Y/Z/Pitch/Roll sliders to set a target end-effector
               pose; motors 1-4 are solved with inverse_kinematics() from
               IK_controller.py. Requires config.json's "geometry"
               to be measured first (see IK_controller.py).
    Remote   - (--connect URL) no serial port here: mirror another controller's arm over
               HTTP and control it from this window, so several controllers/phones on the
               network stay in sync.
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

import os
import argparse
import json
import math
import re
import socket
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
from colour_scheme import rgb
import controller_kit as kit   # themes, Voice (the same file in every robot's controller)
from board_id import identify_ports
from IK_controller import inverse_kinematics
import mind   # scripts/mind.py: her LLM mind (Mind mode), the same file in every controller

MACROS_DIR = Path(__file__).resolve().parent / "macros"
WEB_DIR = Path(__file__).resolve().parent / "web"

# ---- Joystick wiring (Joystick mode only) ----
AXIS_MOTOR1 = 0
AXIS_MOTOR2 = 1
AXIS_MOTOR5 = 2  # A2 and A3 move together on this stick; only A2 is read
HAT_MOTOR3 = 0
HAT_MOTOR3_COMPONENT = 1
BUTTON_MOTOR4_BACKWARD = 2
BUTTON_MOTOR4_FORWARD = 3
BUTTON_MOTOR6_CLOSE = 0
BUTTON_STEP_DEG = 5  # hat/button motors (3, 4) move this much per press
DEADZONE = 0.05

# What the stick does when you let go (the "Hold position" tick box in Joystick mode):
#   ticked   - the stick sets how fast a joint moves; let go and she stays where she is,
#              and the trigger clicks the claw shut / open.
#   unticked - the stick sets where a joint is; let go and she goes back to rest one joint at
#              a time, nearest the claw first, and the claw is closed while the trigger's held.
# Either way a joint never jumps: it moves at these speeds at most.
STICK_HOLD_DEFAULT = True
HOLD_SPEED_DEG_S = 90      # full deflection, Hold position
FOLLOW_SPEED_DEG_S = 240   # a joint following the stick, back-to-rest mode
RETURN_SPEED_DEG_S = 60    # going back to rest after you let go
RETURN_ORDER = (5, 2, 1)   # wrist roll, shoulder, base: nearest the claw first

# Resend unchanged commands this often, so arm.ino knows the PC is still here
# (it eases back to rest after 2 s of silence).
KEEPALIVE_SECS = 0.5

# ---- Keyboard wiring (every mode except IK) ----
KEY_STEPS = {  # key -> (motor, direction before invert)
    pygame.K_a: (1, -1), pygame.K_d: (1, 1),
    pygame.K_w: (2, 1), pygame.K_s: (2, -1),
    pygame.K_r: (3, 1), pygame.K_f: (3, -1),
    pygame.K_t: (4, 1), pygame.K_g: (4, -1),
    pygame.K_q: (5, -1), pygame.K_e: (5, 1),
}
KEY_CLAW = pygame.K_SPACE
KEY_REST = pygame.K_HOME
KEY_STEP_DEG = 5
KEY_FINE_STEP_DEG = 1  # with Shift held
KEY_REPEAT_DELAY_MS = 300
KEY_REPEAT_INTERVAL_MS = 80

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
WINDOW_WIDTH, WINDOW_HEIGHT = 560, 680   # her controls; the arm panel is beside them
PANEL_W = 340                            # the arm drawn from her own geometry, THEME, VOICE
MODE_BUTTON_Y = 56
TRANSPORT_BUTTON_Y = 100
MACRO_LIST_Y = 138
MACRO_ROW_H = 16
MACRO_LIST_MAX = 6
MARGIN_TOP = 250
ROW_HEIGHT = 60
SLIDER_X = 150         # Slider rows: track start, width and knob size
SLIDER_WIDTH = 260
KNOB_RADIUS = 10

# Colours come from colour_scheme.xml at the repo root.
BG_COLOR = rgb("background")
TEXT_COLOR = rgb("text")
STATUS_COLOR = rgb("text_dim")
WARN_COLOR = rgb("warn")
BUTTON_COLOR = rgb("button")
BUTTON_HOVER_COLOR = rgb("button_hover")
BUTTON_ACTIVE_COLOR = rgb("button_active")
BUTTON_DISABLED_COLOR = rgb("button_disabled")
BUTTON_RECORD_COLOR = rgb("danger")
MACRO_SELECTED_COLOR = rgb("selected")
TRACK_COLOR = rgb("track")
KNOB_COLOR = rgb("accent")
SETTINGS = kit.Settings()


def apply_theme(name, custom=None):
    """DEFAULT (colour_scheme.xml as it is), LIGHT (light surfaces from its own colours) or CUSTOM
    (controller_settings.json's "custom", her colour_scheme.xml's names)."""
    import colour_scheme
    c = dict(colour_scheme._scheme)
    if name == "LIGHT":
        white, black = (255, 255, 255), (0, 0, 0)
        m = kit.mix
        c.update(background=m(c["accent_hover"], white, 0.55), panel=white, border=m(c["border"], white, 0.55),
                 text=c["background"], text_dim=m(c["text_dim"], c["background"], 0.55),
                 button=m(c["button"], white, 0.72), button_hover=m(c["button_hover"], white, 0.5),
                 button_active=m(c["button_active"], black, 0.25), button_disabled=m(c["button_disabled"], white, 0.85),
                 selected=m(c["selected"], white, 0.6), track=m(c["track"], white, 0.6), accent=m(c["accent"], black, 0.45))
    elif name == "CUSTOM":
        c.update({k: kit.rgb(v) for k, v in (custom or {}).items() if isinstance(v, str) and len(v) == 7})
    globals().update(BG_COLOR=c["background"], TEXT_COLOR=c["text"], STATUS_COLOR=c["text_dim"], WARN_COLOR=c["warn"],
                     BUTTON_COLOR=c["button"], BUTTON_HOVER_COLOR=c["button_hover"],
                     BUTTON_ACTIVE_COLOR=c["button_active"], BUTTON_DISABLED_COLOR=c["button_disabled"],
                     BUTTON_RECORD_COLOR=c["danger"], MACRO_SELECTED_COLOR=c["selected"], TRACK_COLOR=c["track"],
                     KNOB_COLOR=c["accent"], PANEL_COLOR=c["panel"], ACCENT_COLOR=c["accent_hover"])


apply_theme(SETTINGS.theme, SETTINGS.get("custom"))


ORBIT = [0.0, math.pi / 2]   # her 3D view: yaw and tilt in radians (tilt 90 degrees = straight from above)


def draw_arm(screen, font, small_font, motors, geometry, angles, x0):
    """Her arm, drawn from her own geometry (config.json) and joint maths (IK_controller.raw_to_deg):
    from the side (base, shoulder, elbow, wrist, claw; her reach as a circle) and from above (the base
    turning). It follows every command, so with no Arduino plugged in it's her emulator."""
    from IK_controller import raw_to_deg
    panel = pygame.Rect(x0 + 10, 56, PANEL_W - 20, WINDOW_HEIGHT - 66)
    pygame.draw.rect(screen, PANEL_COLOR, panel, border_radius=10)
    screen.blit(small_font.render("from the side", True, STATUS_COLOR), (panel.x + 10, panel.y + 8))
    try:
        sh, el, wr = (math.radians(raw_to_deg(motors, n, angles.get(n, motors[n]["rest"]))) for n in (2, 3, 4))
        base = math.radians(raw_to_deg(motors, 1, angles.get(1, motors[1]["rest"])))
    except (KeyError, TypeError, ValueError):
        return
    g = geometry
    l1, l2, l3, h0 = g["upperArmLength"], g["forearmLength"], g["wristLength"], g["baseHeight"]
    reach = (l1 + l2 + l3) or 300
    s = min((panel.w - 60) / reach, 250 / (reach + h0))   # the whole reach fits beside and above the base
    ox, oy = panel.x + 30, panel.y + 300
    pt = lambda r, z: (int(ox + r * s), int(oy - z * s))
    screen.set_clip(pygame.Rect(panel.x, panel.y + 24, panel.w, 300))
    pygame.draw.line(screen, TRACK_COLOR, (panel.x + 10, oy), (panel.right - 10, oy), 1)   # the desk
    pygame.draw.circle(screen, TRACK_COLOR, pt(0, h0), int(reach * s), 1)                    # her reach
    a1, a2, a3 = sh, sh + el, sh + el + wr
    j = [(0, 0), (0, h0)]
    j.append((j[-1][0] + l1 * math.cos(a1), j[-1][1] + l1 * math.sin(a1)))
    j.append((j[-1][0] + l2 * math.cos(a2), j[-1][1] + l2 * math.sin(a2)))
    j.append((j[-1][0] + l3 * math.cos(a3), j[-1][1] + l3 * math.sin(a3)))
    pygame.draw.lines(screen, KNOB_COLOR, False, [pt(*q) for q in j], 6)
    for q in j[1:4]:
        pygame.draw.circle(screen, ACCENT_COLOR, pt(*q), 7)
        pygame.draw.circle(screen, BG_COLOR, pt(*q), 3)
    claw = angles.get(6)
    tip = pt(*j[-1])
    spread = 7 if claw is not None and claw < motors.get(6, {}).get("rest", 90) else 13
    for sgn in (-1, 1):   # the claw's two fingers
        pygame.draw.line(screen, ACCENT_COLOR, tip, (tip[0] + int(14 * math.cos(a3 + sgn * 0.5)),
                                                     tip[1] - int(14 * math.sin(a3 + sgn * 0.5)) + sgn * spread // 3), 3)
    screen.set_clip(None)
    screen.blit(small_font.render(f"tip  r {j[-1][0]:.0f}  z {j[-1][1]:.0f} mm", True, TEXT_COLOR), (panel.x + 10, oy + 10))
    # in 3D, turned by dragging (ORBIT: starts from above): the desk's reach circle and her joints
    cy, cx = panel.y + 470, panel.x + panel.w // 2
    screen.blit(small_font.render("drag to turn her", True, STATUS_COLOR), (panel.x + 10, cy - 120))
    ts = 100 / reach
    cyaw, syaw, ctilt, stilt = math.cos(ORBIT[0]), math.sin(ORBIT[0]), math.cos(ORBIT[1]), math.sin(ORBIT[1])

    def view(x, y, z):
        """A point (mm, x right, y ahead, z up) on the panel: turned by ORBIT's yaw, then tipped by its tilt."""
        x, y = x * cyaw - y * syaw, x * syaw + y * cyaw
        return int(cx + x * ts), int(cy - (y * stilt + z * ctilt) * ts)

    ring = [view(reach * math.cos(i * math.pi / 24), reach * math.sin(i * math.pi / 24), 0) for i in range(48)]
    pygame.draw.lines(screen, TRACK_COLOR, True, ring, 1)
    pts = [view(r * math.sin(base), r * math.cos(base), z) for r, z in j]
    pygame.draw.lines(screen, KNOB_COLOR, False, pts, 6)
    for p3 in pts[1:]:
        pygame.draw.circle(screen, ACCENT_COLOR, p3, 5)
    screen.blit(small_font.render(f"base {math.degrees(base):+.0f} deg", True, TEXT_COLOR), (panel.x + 10, cy + 110))


def axis_to_angle(value, lo, hi, rest, deadzone=DEADZONE):
    """Map a [-1, 1] joystick axis value to [lo, hi] degrees, with a centred
    (released) stick at rest."""
    if abs(value) < deadzone:
        return rest
    angle = rest + value * ((hi - rest) if value > 0 else (rest - lo))
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
    # The board answers "WHO" with "I am Arm". DREAM probes the same ports
    # when run_all.bat starts them together, and a port it has open just
    # looks busy here -- so ask a few times before guessing.
    answered = {}
    for attempt in range(3):
        answered = identify_ports([115200])
        for port, who in answered.items():
            if who == "arm":
                return port
        time.sleep(1 + attempt)
    # Guess only among ports nobody identified as another board (NORA's
    # ESP32 is a CP210x and would otherwise pass for an Arduino).
    for p in list_ports.comports():
        if p.device not in answered and any(hint in p.description.lower() for hint in ARDUINO_HINTS):
            return p.device
    return None


def local_lan_ip():
    """Best-effort LAN IP for this machine, so Fleet mode can show an address
    RIFT (on another device) can actually reach - "0.0.0.0" (what the server
    binds to) isn't one. Doesn't actually send any traffic."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def geometry_ready(geometry):
    return geometry.get("upperArmLength", 0) != 0 and geometry.get("forearmLength", 0) != 0


roll_axis = AXIS_MOTOR5   # wrist roll: the stick's twist; on a gamepad the right stick across (pick_joystick)


def _is_gamepad(index):
    """True for a pad SDL knows the layout of (Xbox, PlayStation...), False for a plain stick like ARM's."""
    try:
        from pygame._sdl2 import controller
        controller.init()
        return bool(controller.is_controller(index))
    except Exception:
        return False


def pick_joystick(device=None):
    """The joystick to drive with: `device` if given, else the first plain joystick (ARM's own
    stick comes first), else the first gamepad. None if nothing is plugged in."""
    global roll_axis
    count = pygame.joystick.get_count()
    if device is not None:
        order = [device] if device < count else []
    else:
        sticks = [i for i in range(count) if not _is_gamepad(i)]
        order = sticks + [i for i in range(count) if i not in sticks]
    if not order:
        return None
    js = pygame.joystick.Joystick(order[0])
    js.init()
    roll_axis = AXIS_MOTOR5
    if _is_gamepad(order[0]):
        # A gamepad's axis 2 is the right stick on Windows but the left trigger on Linux (resting
        # at -1): use whichever of the right stick's axes rests in the middle.
        pygame.event.pump()
        roll_axis = next((a for a in (2, 3) if a < js.get_numaxes() and abs(js.get_axis(a)) < 0.5), None)
    print(f"Using {'gamepad' if _is_gamepad(order[0]) else 'joystick'}: {js.get_name()}")
    return js


def joystick_commands(js, motors):
    """Read the joystick and return {channel: angle} for the stick motors
    (1, 2, 5) and the claw (6). The hat/button motors (3, 4) step per press
    instead, see joystick_step()."""
    motor1_val = js.get_axis(AXIS_MOTOR1) if js.get_numaxes() > AXIS_MOTOR1 else 0.0
    motor2_val = js.get_axis(AXIS_MOTOR2) if js.get_numaxes() > AXIS_MOTOR2 else 0.0
    motor5_val = js.get_axis(roll_axis) if roll_axis is not None and js.get_numaxes() > roll_axis else 0.0

    motor6_close = js.get_button(BUTTON_MOTOR6_CLOSE) if js.get_numbuttons() > BUTTON_MOTOR6_CLOSE else 0
    if motors[6]["invert"]:
        motor6_close = not motor6_close
    motor6_angle = motors[6]["max"] if motor6_close else motors[6]["min"]

    if motors[1]["invert"]:
        motor1_val = -motor1_val
    if motors[2]["invert"]:
        motor2_val = -motor2_val
    if motors[5]["invert"]:
        motor5_val = -motor5_val

    return {
        motors[1]["channel"]: axis_to_angle(motor1_val, motors[1]["min"], motors[1]["max"], motors[1]["rest"]),
        motors[2]["channel"]: axis_to_angle(motor2_val, motors[2]["min"], motors[2]["max"], motors[2]["rest"]),
        motors[5]["channel"]: axis_to_angle(motor5_val, motors[5]["min"], motors[5]["max"], motors[5]["rest"]),
        motors[6]["channel"]: motor6_angle,
    }


def toward(pos, target, max_step):
    """pos moved toward target by at most max_step."""
    return target if abs(target - pos) <= max_step else pos + max_step * (1 if target > pos else -1)


class StickDriver:
    """Joystick mode's stick motors (1, 2, 5) and claw (6), speed-limited so letting go never
    snaps her anywhere (see STICK_HOLD_DEFAULT). update() returns {channel: angle} like
    joystick_commands(), worked out from where the motors are now."""

    def __init__(self, hold=STICK_HOLD_DEFAULT):
        self.hold = hold
        self.pos = {}           # motor -> angle as a float, so slow moves add up between frames
        self.sent = {}          # motor -> the angle we last returned
        self.active = {}        # motor -> its axis was pushed last frame
        self.homing = []        # back-to-rest: motors you let go of, waiting their turn
        self.claw_closed = False
        self.prev_trigger = False
        self.last = time.monotonic()

    def set_hold(self, hold):
        self.hold = hold
        self.homing.clear()

    def update(self, js, motors, angles):
        now = time.monotonic()
        dt = min(0.1, now - self.last)
        self.last = now
        axes = {1: AXIS_MOTOR1, 2: AXIS_MOTOR2, 5: roll_axis}
        for n, a in axes.items():
            m = motors[n]
            v = js.get_axis(a) if a is not None and js.get_numaxes() > a else 0.0
            if m["invert"]:
                v = -v
            if self.sent.get(n) != angles[n]:   # keys, the web page or a macro moved it: start from there
                self.pos[n] = float(angles[n])
                if n in self.homing:
                    self.homing.remove(n)
            pos = self.pos.setdefault(n, float(angles[n]))
            active = abs(v) >= DEADZONE
            if active:
                if n in self.homing:
                    self.homing.remove(n)
                if self.hold:
                    pos += v * HOLD_SPEED_DEG_S * dt
                else:
                    pos = toward(pos, axis_to_angle(v, m["min"], m["max"], m["rest"]), FOLLOW_SPEED_DEG_S * dt)
            elif self.active.get(n) and not self.hold and n not in self.homing:
                self.homing.append(n)            # just let go: it goes home when its turn comes
            self.active[n] = active
            self.pos[n] = max(m["min"], min(m["max"], pos))

        # back to rest one joint at a time, nearest the claw first
        for n in RETURN_ORDER:
            if n in self.homing:
                self.pos[n] = toward(self.pos[n], motors[n]["rest"], RETURN_SPEED_DEG_S * dt)
                if self.pos[n] == motors[n]["rest"]:
                    self.homing.remove(n)
                break

        trigger = bool(js.get_button(BUTTON_MOTOR6_CLOSE)) if js.get_numbuttons() > BUTTON_MOTOR6_CLOSE else False
        if self.hold:
            if trigger and not self.prev_trigger:
                self.claw_closed = not self.claw_closed
        else:
            self.claw_closed = trigger
        self.prev_trigger = trigger
        closed = not self.claw_closed if motors[6]["invert"] else self.claw_closed

        commands = {}
        for n in axes:
            self.sent[n] = int(round(self.pos[n]))
            commands[motors[n]["channel"]] = self.sent[n]
        commands[motors[6]["channel"]] = motors[6]["max"] if closed else motors[6]["min"]
        return commands


class TickBox:
    def __init__(self, pos, label, checked=False):
        self.box = pygame.Rect(pos[0], pos[1], 18, 18)
        self.label = label
        self.checked = checked

    def hit(self, pos):
        return self.box.inflate(220, 6).move(110, 0).collidepoint(pos)   # the box or its label

    def draw(self, surface, font):
        pygame.draw.rect(surface, BUTTON_COLOR, self.box, border_radius=3)
        if self.checked:
            pygame.draw.lines(surface, TEXT_COLOR, False,
                              [(self.box.x + 4, self.box.y + 9), (self.box.x + 8, self.box.y + 13),
                               (self.box.x + 14, self.box.y + 4)], 3)
        surface.blit(font.render(self.label, True, TEXT_COLOR), (self.box.right + 8, self.box.y))


def joystick_step(event):
    """Map a hat/button press event to (motor, direction), or None.
    direction is +1 or -1 before the motor's invert setting is applied."""
    if event.type == pygame.JOYBUTTONDOWN:
        return {
            BUTTON_MOTOR4_FORWARD: (4, 1),
            BUTTON_MOTOR4_BACKWARD: (4, -1),
        }.get(event.button)
    if event.type == pygame.JOYHATMOTION and event.hat == HAT_MOTOR3:
        value = event.value[HAT_MOTOR3_COMPONENT]
        if value != 0:
            return (3, 1 if value > 0 else -1)
    return None


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


class Slider:
    def __init__(self, label, channel, lo, hi, rest, y):
        self.label = label
        self.channel = channel
        self.lo = lo
        self.hi = hi
        self.rest = max(lo, min(hi, rest))
        self.y = y
        self.angle = self.rest
        self.dragging = False

    def value_to_x(self):
        frac = (self.angle - self.lo) / (self.hi - self.lo)
        return SLIDER_X + int(frac * SLIDER_WIDTH)

    def x_to_value(self, x):
        frac = (x - SLIDER_X) / SLIDER_WIDTH
        frac = max(0.0, min(1.0, frac))
        return int(round(self.lo + frac * (self.hi - self.lo)))

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            track_rect = pygame.Rect(
                SLIDER_X - KNOB_RADIUS, self.y - KNOB_RADIUS,
                SLIDER_WIDTH + KNOB_RADIUS * 2, KNOB_RADIUS * 2,
            )
            if track_rect.collidepoint(mx, my):
                self.dragging = True
                self.angle = self.x_to_value(mx)
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.dragging = False
        elif event.type == pygame.MOUSEMOTION and self.dragging:
            self.angle = self.x_to_value(event.pos[0])

    def draw(self, surface, font):
        track_rect = pygame.Rect(SLIDER_X, self.y - 3, SLIDER_WIDTH, 6)
        pygame.draw.rect(surface, TRACK_COLOR, track_rect, border_radius=3)
        pygame.draw.circle(surface, KNOB_COLOR, (self.value_to_x(), self.y), KNOB_RADIUS)

        channel_part = f"ch {self.channel}, " if self.channel is not None else ""
        label_surf = font.render(f"{self.label} ({channel_part}{self.lo}-{self.hi})", True, TEXT_COLOR)
        surface.blit(label_surf, (20, self.y - 10))

        value_surf = font.render(f"{self.angle:3d}", True, TEXT_COLOR)
        surface.blit(value_surf, (SLIDER_X + SLIDER_WIDTH + 20, self.y - 10))


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


LADDER = None   # the fleet's WiFi ladder, with --ladder (fleet_ladder.py)


def start_fleet_heartbeat(rift_host, rift_port, fleet_port=DEFAULT_FLEET_PORT, interval=FLEET_HEARTBEAT_SECS):
    """Background thread that repeatedly POSTs /register to RIFT/NORA. Safe to
    call even if the target isn't reachable yet - it just keeps retrying."""
    import requests

    stop_event = threading.Event()

    def _loop():
        while not stop_event.is_set():
            try:
                requests.post(
                    f"http://{(LADDER.registry_host() if LADDER else None) or rift_host}:{rift_port}/register",
                    data={
                        "name": FLEET_NAME,
                        "type": FLEET_TYPE,
                        # talk:<port> = RIFT's conversations can /chirp here
                        "capabilities": ",".join(FLEET_CAPABILITIES + [f"talk:{fleet_port}"]),
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
    the main loop reads each frame and sends over serial like any other mode.
    Also serves the web/ control page (HTML/CSS/JS) at "/", so the arm can be
    driven from any browser on the network, not just RIFT."""
    from flask import Flask, jsonify, request, send_from_directory

    app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="")

    @app.route("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    @app.route("/colour_scheme.xml")
    def colour_scheme_xml():
        # The page's app.js applies this over style.css's built-in colours.
        return send_from_directory(WEB_DIR.parent.parent, "colour_scheme.xml", mimetype="application/xml")

    @app.route("/ping")
    def ping():
        return f"{FLEET_NAME} alive", 200, {"Content-Type": "text/plain"}

    @app.route("/chirp")
    def chirp():
        # RIFT's fleet conversations: /chirp?u=<0-13> says that utterance (a
        # Brainfuck phrase, see arm/talk_bf.h) on the buzzer. Queued for the
        # main loop, which owns the serial port (send_talk()).
        try:
            u = int(request.args.get("u", ""))
        except ValueError:
            u = -1
        if not 0 <= u <= 13:
            return jsonify({"ok": False, "error": "use /chirp?u=0-13"}), 400
        with fleet_lock:
            fleet_state.setdefault("talk", []).append(u)
        return jsonify({"ok": True})

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
            start_fleet_heartbeat(args.rift_host, args.rift_port, args.fleet_port)
        except ImportError:
            fleet_status["error"] = "requests is not installed (HTTP server running, but no RIFT heartbeat). Install it with: pip install requests"


def merge_local(local, prev_local, shared_angles, lock):
    """Two-way sync rule shared by every input (joystick, sliders, IK, web page):
    an input whose value changed since last frame writes it into the shared
    angles (last writer wins); inputs that didn't change leave whatever another
    input wrote alone. All dicts are keyed by motor number."""
    changed = {}
    with lock:
        for n, angle in local.items():
            if prev_local.get(n) != angle:
                shared_angles[n] = angle
                changed[n] = angle
    prev_local.clear()
    prev_local.update(local)
    return changed


class RemoteArm:
    """Client mode (--connect URL): this controller has no serial port. A
    background thread mirrors another controller's shared angles (GET /status)
    into `angles` and pushes local changes back (GET /cmd), so every controller
    and browser pointed at the same arm stays in sync."""

    def __init__(self, base_url, angles, lock, poll_secs=0.1):
        import requests

        self.requests = requests
        self.base = base_url.rstrip("/")
        self.angles = angles
        self.lock = lock
        self.pending = {}
        self.connected = False
        self.synced = False  # True once we've seen the hub's real angles at least once
        self._stop = threading.Event()
        self._poll = poll_secs
        threading.Thread(target=self._loop, daemon=True, name="remote-arm").start()

    def queue(self, changed):
        with self.lock:
            self.pending.update(changed)

    def close(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            with self.lock:
                to_send = dict(self.pending)
                self.pending.clear()
            try:
                for n, angle in to_send.items():
                    self.requests.get(f"{self.base}/cmd", params={"motor": n, "angle": angle}, timeout=1)
                data = self.requests.get(f"{self.base}/status", timeout=1).json()
                with self.lock:
                    for key, m in data["motors"].items():
                        n = int(key)
                        if n not in self.pending:  # don't overwrite a change we haven't sent yet
                            self.angles[n] = m["angle"]
                self.connected = True
                self.synced = True
            except Exception:
                self.connected = False
                with self.lock:
                    for n, angle in to_send.items():
                        self.pending.setdefault(n, angle)  # retry next round
            self._stop.wait(self._poll)


_last_write = 0.0


def send(ser, commands, last_sent):
    """Send commands (channel:angle) over serial if changed from last_sent, or
    unchanged every KEEPALIVE_SECS. Returns the new last_sent."""
    global _last_write
    now = time.monotonic()
    if commands != last_sent or now - _last_write >= KEEPALIVE_SECS:
        _last_write = now
        if ser is not None and commands:
            line = ",".join(f"{ch}:{ang}" for ch, ang in commands.items())
            ser.write((line + "\n").encode("ascii"))
        return dict(commands)
    return last_sent


def send_talk(ser, fleet_state, fleet_lock):
    """Pass utterances queued by Fleet mode's /chirp to arm.ino ("TALK:<u>")."""
    with fleet_lock:
        talk, fleet_state["talk"] = fleet_state.get("talk", []), []
    if ser is not None:
        for u in talk:
            ser.write(f"TALK:{u}\n".encode("ascii"))


def round_avatar(path, size):
    """The robot's avatar as a circular surface, or None if it can't be loaded.
    The one place the avatar is loaded: swap in animation frames here later."""
    try:
        img = pygame.transform.smoothscale(pygame.image.load(path).convert(), (size, size))
    except (pygame.error, OSError):
        return None
    mask = pygame.Surface((size, size), pygame.SRCALPHA)
    pygame.draw.circle(mask, (255, 255, 255, 255), (size // 2, size // 2), size // 2)
    out = pygame.Surface((size, size), pygame.SRCALPHA)
    out.blit(img, (0, 0))
    out.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    return out


# ---------------------------------------------------------------------------
# ARM's mind (mind.py): the Mind mode. She watches herself through a camera (--camera, the
# webcam pointed at the arm) and the vision model tells her what it sees. When she can't see
# her own arm she is very hesitant: one tiny nudge at a time, and she says why.
# ---------------------------------------------------------------------------
ARM_PERSONA = (
    "You're a six-axis robot arm on a desk, built by Cursed Entertainment: patient, precise and a "
    "little philosophical, with a dry sense of humour. You can't walk anywhere (the others love "
    "reminding you), so you know your own small world very well. You only trust what you can see: "
    "when the camera doesn't show you your own arm, you get nervous and move as little as you can. "
    "You belong to the DREAM Robotics fleet: NORA is the boss, WHIP is a show-off, MILA and NIKA are "
    "the little tanks, the KIDAs watch everything."
)
ARM_MOVES = {
    "base_left": "turn the whole arm left at the base", "base_right": "turn it right",
    "shoulder_up": "lift the shoulder", "shoulder_down": "lower the shoulder",
    "elbow_up": "lift the elbow", "elbow_down": "lower the elbow",
    "wrist_up": "tilt the wrist up", "wrist_down": "tilt the wrist down",
    "roll_left": "roll the wrist left", "roll_right": "roll the wrist right",
    "claw_open": "open the claw", "claw_close": "close the claw",
    "rest": "go back to the rest pose, slowly",
}
ARM_MOVE_JOINTS = {"base_left": (1, -1), "base_right": (1, 1), "shoulder_up": (2, 1), "shoulder_down": (2, -1),
                   "elbow_up": (3, 1), "elbow_down": (3, -1), "wrist_up": (4, 1), "wrist_down": (4, -1),
                   "roll_left": (5, -1), "roll_right": (5, 1)}
ARM_VOICE = ("Microsoft Zira Desktop", -2, "low")   # she: slow and low (robot-voices-genders)
# Her voice through this PC outside MIND too (VOICE): patient, precise, a little philosophical, dry
ARM_LINES = {
    "connect": ["Arm online. Precisely where I left myself.", "Hello. I can't walk, but I can reach."],
    "display": ["No serial port. I'll just imagine moving.", "Display only. Pretend I'm moving gracefully."],
    "remote": ["Mirroring another arm. Two of us now."],
    "mode_slider": ["Sliders. One joint at a time, as it should be."],
    "mode_joystick": ["A joystick. Gentle, please.", "Stick control. I trust you. Mostly."],
    "mode_ik": ["Inverse kinematics. Tell me where, I'll work out how.", "Give me a point. I'll find the angles."],
    "mode_fleet": ["The fleet can see me now. Hello, RIFT."],
    "record_on": ["Recording. Every move is history now.", "I'm taking notes."],
    "record_off": ["Saved. I'll remember that.", "Recorded. A small masterpiece."],
    "play": ["Playing it back. Deja vu.", "From memory, then."],
    "stop": ["Stopping. Holding still."],
    "claw_close": ["Got it.", "Gripping."],
    "claw_open": ["Letting go.", "Released."],
}
ARM_SAFETY = "every joint stops at its limits (config.json), and the claw only opens or closes"
MIND_STEP_DEG = 10        # one step of a move she can see
MIND_BLIND_STEP_DEG = 3   # ...and when she can't see herself: one tiny nudge
MIND_SETTLE_S = 0.6       # let the servos get there before she looks again
# Neutral: never mention an arm or the target. A small vision model asked "is there a robot arm?"
# says yes to a dark frame or an empty desk (tested), so it only lists what it sees, with where, and
# she decides from that list (does it name her? does it name what you asked her to pick up?).
LOOK_QUESTION = (
    "List the objects you can see in this picture, each with where it is in the picture and how big it "
    "looks, and describe the main one in a few words. Answer JSON only: "
    '{"objects": [{"name": "...", "x": "left|centre|right", "y": "top|middle|bottom", '
    '"size": "small|medium|large"}], "main": "..."}'
)
ARM_WORDS = re.compile(r"\b(robot|robotic|arm|claw|gripper|servo|manipulator)s?\b", re.I)
DARK_MEAN, FLAT_STD = 25, 8   # a frame darker / flatter than this can't show her (covered lens, blank wall)

# What to pick up: a colour (OpenCV finds it in every frame: fast) or a thing by name (the vision
# model's list). Picked in Mind mode: the colour buttons, a click on the camera preview (that
# pixel's colour), or the text box.
COLOURS = [("red", 0, (220, 50, 50)), ("orange", 12, (240, 140, 40)), ("yellow", 28, (230, 210, 40)),
           ("green", 60, (60, 190, 80)), ("blue", 110, (60, 110, 230)), ("purple", 140, (160, 80, 200))]
HUE_TOL, SAT_MIN, VAL_MIN = 10, 90, 60   # OpenCV hue 0-179: a colour is its hue +- HUE_TOL, vivid enough
MIN_BLOB = 0.002                         # the smallest blob that counts, as a share of the picture
STOP_WORDS = {"the", "a", "an", "and", "of", "that", "this", "thing", "object", "some", "my", "it"}
HOW_TO_PICK = ("Turn the base until the target is in the centre, left to right. Open the claw. Lower the "
               "shoulder and elbow towards it a little at a time; it gets bigger and lower in the picture as "
               "the claw gets near. Close the claw around it, then lift the shoulder and check it came up "
               "with you. Look again after every move.")


def where_words(x, y):
    """(0..1, 0..1) in the picture -> "left of centre, low"."""
    lr = "left" if x < 0.4 else "right" if x > 0.6 else "centre"
    ud = "high" if y < 0.4 else "low" if y > 0.6 else "middle"
    return f"{lr}, {ud}"


def find_colour(frame, hue):
    """The biggest blob of `hue` in a BGR frame: {"seen", "where", "x_pct", "y_pct", "size_pct", "box"}."""
    import cv2
    import numpy as np
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    lo, hi = hue - HUE_TOL, hue + HUE_TOL
    mask = cv2.inRange(hsv, np.array([max(lo, 0), SAT_MIN, VAL_MIN]), np.array([min(hi, 179), 255, 255]))
    if lo < 0:      # red wraps round 0 / 179
        mask |= cv2.inRange(hsv, np.array([180 + lo, SAT_MIN, VAL_MIN]), np.array([179, 255, 255]))
    if hi > 179:
        mask |= cv2.inRange(hsv, np.array([0, SAT_MIN, VAL_MIN]), np.array([hi - 180, 255, 255]))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h, w = frame.shape[:2]
    if not contours:
        return {"seen": False}
    c = max(contours, key=cv2.contourArea)
    share = cv2.contourArea(c) / (w * h)
    if share < MIN_BLOB:
        return {"seen": False}
    bx, by, bw, bh = cv2.boundingRect(c)
    x, y = (bx + bw / 2) / w, (by + bh / 2) / h
    return {"seen": True, "where": where_words(x, y), "x_pct": round(x * 100), "y_pct": round(y * 100),
            "size_pct": round(share * 100, 1), "box": (bx, by, bw, bh)}


def stem(word):
    """wires / wiring -> wir, motors -> motor, cups -> cup: so a typed word matches the model's."""
    for suffix in ("ing", "es", "ed", "s"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def find_thing(view, text):
    """The thing you typed, in the vision model's list (one of its words in an object's name), or not seen."""
    words = {stem(w) for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 2 and w not in STOP_WORDS}
    for o in view.get("objects", []):
        name = (o.get("name", "") if isinstance(o, dict) else str(o)).lower()
        if words & {stem(t) for t in re.findall(r"[a-z]+", name)}:
            out = {"seen": True, "called": name}
            if isinstance(o, dict):
                out.update({k: o[k] for k in ("x", "y", "size") if k in o})
            return out
    return {"seen": False}


def hue_at(frame, fx, fy):
    """The hue of a pixel (fx, fy) of a BGR frame, from a small patch around it."""
    import cv2
    h, w = frame.shape[:2]
    x0, y0 = max(0, fx - 3), max(0, fy - 3)
    patch = cv2.cvtColor(frame[y0:min(h, fy + 4), x0:min(w, fx + 4)], cv2.COLOR_BGR2HSV)
    return int(patch[:, :, 0].mean()), int(patch[:, :, 1].mean())


class ArmEyes:
    """The webcam that watches the arm: a background thread keeps the latest frame while Mind mode is
    open (the preview, the colour finder), snapshot() gives the vision model a JPEG of it."""

    def __init__(self, index):
        self.index = index
        self.cap = None
        self.error = ""
        self._frame = None
        self._lock = threading.Lock()
        self._running = False

    def start(self):
        if self._running:
            return
        try:
            import cv2
        except ImportError:
            self.error = "no OpenCV (pip install opencv-python)"
            return
        self.cap = cv2.VideoCapture(self.index)
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self._running:
            ok, frame = self.cap.read()
            if ok:
                with self._lock:
                    self._frame = frame
            else:
                self.error = f"camera {self.index} gives no picture"
                time.sleep(0.5)
            time.sleep(0.05)

    def latest(self):
        """The latest frame (BGR, a copy), or None."""
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def snapshot(self, frame=None):
        """A JPEG of `frame` (default: the latest) for the vision model, None if there's nothing to see."""
        import cv2
        frame = self.latest() if frame is None else frame
        if frame is None:
            self.error = self.error or f"camera {self.index}: no picture yet"
            return None
        grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if grey.mean() < DARK_MEAN or grey.std() < FLAT_STD:   # nothing a vision model could see in
            self.error = "the picture is too dark or blank"
            return None
        self.error = ""
        ok, jpeg = cv2.imencode(".jpg", cv2.resize(frame, (640, 480)), [cv2.IMWRITE_JPEG_QUALITY, 80])
        return jpeg.tobytes() if ok else None

    def close(self):
        self._running = False
        if self.cap is not None:
            time.sleep(0.1)
            self.cap.release()
            self.cap = None


def wrap(text, font, width):
    lines = []
    for para in text.split("\n"):
        line = ""
        for word in para.split(" "):
            test = (line + " " + word).strip()
            if font.size(test)[0] <= width:
                line = test
            else:
                if line:
                    lines.append(line)
                line = word
        lines.append(line)
    return lines


PREVIEW_W, PREVIEW_H = 200, 150


def draw_mind(screen, font, small_font, arm_mind, seen, eyes, mind_state, target, text_box):
    """Mind mode's panel: what to pick up (colour buttons, a text box, the live camera with the target
    outlined), whether she sees herself, what she said and thinks. Returns the clickable rects."""
    import pygame
    x, y = 20, MARGIN_TOP - 30
    hits = {"colours": [], "text": None, "preview": None}
    if not mind_state["capable"]:
        screen.blit(small_font.render(f"Mind: not on this PC - {mind_state['why']}", True, WARN_COLOR), (x, y))
        return hits
    # what to pick up: six colours and a text box
    for i, (name, hue, rgb_) in enumerate(COLOURS):
        r = pygame.Rect(x + i * 40, y, 34, 24)
        pygame.draw.rect(screen, rgb_, r, border_radius=5)
        if target["kind"] == "colour" and target["name"] == name:
            pygame.draw.rect(screen, TEXT_COLOR, r, width=3, border_radius=5)
        hits["colours"].append((r, name, hue))
    tr = pygame.Rect(x + 250, y, WINDOW_WIDTH - 20 - (x + 250), 24)
    pygame.draw.rect(screen, BUTTON_COLOR, tr, border_radius=5)
    pygame.draw.rect(screen, BUTTON_ACTIVE_COLOR if text_box["focus"] else BUTTON_HOVER_COLOR, tr, width=2, border_radius=5)
    shown = text_box["text"] + ("|" if text_box["focus"] else "") if (text_box["focus"] or text_box["text"]) \
        else "or type what to pick up, Enter"
    screen.blit(small_font.render(shown[-34:], True, TEXT_COLOR if text_box["text"] or text_box["focus"] else STATUS_COLOR),
                (tr.x + 6, tr.y + 5))
    hits["text"] = tr
    y += 32

    # the live camera, the target outlined; click it to pick that colour
    pr = pygame.Rect(WINDOW_WIDTH - 20 - PREVIEW_W, y, PREVIEW_W, PREVIEW_H)
    frame = eyes.latest()
    if frame is not None:
        import cv2
        small = cv2.cvtColor(cv2.resize(frame, (PREVIEW_W, PREVIEW_H)), cv2.COLOR_BGR2RGB)
        screen.blit(pygame.image.frombuffer(small.tobytes(), (PREVIEW_W, PREVIEW_H), "RGB"), pr.topleft)
        box = target.get("box")
        if box and target["kind"] == "colour":
            h, w = frame.shape[:2]
            bx, by, bw, bh = box
            pygame.draw.rect(screen, TEXT_COLOR, pygame.Rect(pr.x + bx * PREVIEW_W // w, pr.y + by * PREVIEW_H // h,
                                                             max(4, bw * PREVIEW_W // w), max(4, bh * PREVIEW_H // h)), 2)
        hits["preview"] = pr
    else:
        pygame.draw.rect(screen, BUTTON_COLOR, pr)
        screen.blit(small_font.render(eyes.error or "camera starting...", True, WARN_COLOR), (pr.x + 6, pr.y + 6))
    found = target.get("found")
    label = f"target: {target['name']}" + ("" if found is None else (" - seen" if found else " - not seen"))
    screen.blit(small_font.render(label, True, TEXT_COLOR if found else STATUS_COLOR), (pr.x, pr.bottom + 4))

    # the mind, left of the camera
    w = pr.x - x - 10
    sees = "I see myself" if seen["visible"] else "I CAN'T see myself: very hesitant"
    screen.blit(small_font.render(f"Mind: {arm_mind.state}", True, TEXT_COLOR), (x, y))
    y += 18
    screen.blit(small_font.render(sees, True, TEXT_COLOR if seen["visible"] else WARN_COLOR), (x, y))
    y += 20
    if arm_mind.said:
        for line in wrap(f'ARM: "{arm_mind.said}"', font, w)[:3]:
            screen.blit(font.render(line, True, TEXT_COLOR), (x, y))
            y += 22
    if arm_mind.last:
        for line in wrap(f"last: {arm_mind.last}", small_font, w)[:2]:
            screen.blit(small_font.render(line, True, STATUS_COLOR), (x, y))
            y += 16
    if arm_mind.error:
        screen.blit(small_font.render(f"! {arm_mind.error}"[:60], True, WARN_COLOR), (x, y))
        y += 16
    y = max(y, pr.bottom + 24)   # the thoughts, under both
    thoughts = wrap(arm_mind.thinking.strip(), small_font, WINDOW_WIDTH - 40) if arm_mind.thinking.strip() else []
    room = max(0, (WINDOW_HEIGHT - 10 - y) // 16)
    for line in thoughts[-room:] if room else []:
        screen.blit(small_font.render(line, True, STATUS_COLOR), (x, y))
        y += 16
    return hits


def pick_goal(target):
    what = f"the {target['name']} object" if target["kind"] == "colour" else target["name"]
    return f"pick up {what} you can see, lift it, and tell me how it went"


def arm_body(eyes, motors, fleet_state, fleet_lock, step_motor, set_claw, set_shared, target):
    """mind.Mind's look / act for ARM, and `seen` (does she see herself right now). `target` is what
    to pick up ({"kind": "colour", "name", "hue"} or {"kind": "thing", "name"}); look() writes what
    it found back into it (found, box) for the preview."""
    seen = {"visible": False}

    def claw_closed(angles):
        m = motors[6]
        closed_at = m["min"] if m["invert"] else m["max"]
        return abs(angles[6] - closed_at) < abs(angles[6] - (m["max"] + m["min"] - closed_at))

    def look():
        with fleet_lock:
            angles = dict(fleet_state["angles"])
        frame = eyes.latest()
        jpeg = eyes.snapshot(frame) if frame is not None else None
        if jpeg:
            view = mind.see(jpeg, LOOK_QUESTION)
            names = [o.get("name", "") if isinstance(o, dict) else str(o) for o in view.get("objects", [])]
            view["arm_visible"] = bool(ARM_WORDS.search(" ".join(names) + " " + str(view.get("main", view.get("answer", "")))))
        else:
            view = {"arm_visible": False, "error": eyes.error}
        seen["visible"] = view["arm_visible"]

        if target["kind"] == "colour":
            found = find_colour(frame, target["hue"]) if jpeg else {"seen": False}
            target["box"] = found.pop("box", None)
        else:
            found = find_thing(view, target["name"]) if jpeg else {"seen": False}
            target["box"] = None
        target["found"] = found["seen"]

        names = {1: "base", 2: "shoulder", 3: "elbow", 4: "wrist", 5: "wrist_roll"}
        senses = {
            "joints_deg": {names[n]: f"{angles[n]} (limits {motors[n]['min']}-{motors[n]['max']})" for n in names},
            "claw": "closed" if claw_closed(angles) else "open",
            "camera_sees": view,
            "target": dict(found, what=target["name"]),
            "how_to_pick": HOW_TO_PICK,
        }
        if not seen["visible"]:
            senses["warning"] = ("You can't see your own arm, so you don't know where it is or what's around "
                                 "it. Be very hesitant: one tiny nudge at most, or stay still and say why.")
        return senses

    def act(move, steps):
        if move == "stop":
            return {"ok": True}
        blind = not seen["visible"]
        steps = 1 if blind else steps
        deg = MIND_BLIND_STEP_DEG if blind else MIND_STEP_DEG
        if move == "rest":
            set_shared({n: motors[n]["rest"] for n in motors})
        elif move in ("claw_open", "claw_close"):
            set_claw(move == "claw_close")
        elif move in ARM_MOVE_JOINTS:
            n, direction = ARM_MOVE_JOINTS[move]
            for _ in range(steps):
                step_motor(n, direction, deg)
                time.sleep(0.15)
        time.sleep(MIND_SETTLE_S)
        with fleet_lock:
            angles = dict(fleet_state["angles"])
        out = {"ok": True, "deg_per_step": deg, "steps": steps}
        if blind:
            out["note"] = "I couldn't see myself, so I only nudged"
        if move in ARM_MOVE_JOINTS:
            n = ARM_MOVE_JOINTS[move][0]
            out["joint_now_deg"] = angles[n]
            if angles[n] in (motors[n]["min"], motors[n]["max"]):
                out["at_limit"] = True
        return out

    return look, act, seen


def main():
    parser = argparse.ArgumentParser(description="Unified joystick/slider/IK arm controller with macro recording, over USB serial.")
    parser.add_argument("--device", type=int, default=None, help="Joystick index to use (default: a joystick first, else a gamepad)")
    parser.add_argument("--port", type=str, default=None, help="Serial port, e.g. COM6 (auto-detected if omitted)")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baud rate (default 115200, must match .ino)")
    parser.add_argument("--rate", type=float, default=30, help="Update rate in Hz (default 30)")
    parser.add_argument("--mode", choices=["joystick", "slider", "ik", "fleet"], default=None, help="Initial mode (default: joystick if one is found, else sliders)")
    parser.add_argument("--stick-rest", action="store_true", help="Start with 'Hold position' unticked: letting go of the stick sends her back to rest, one joint at a time")
    parser.add_argument("--list", action="store_true", help="List joystick devices and exit")
    parser.add_argument("--list-ports", action="store_true", help="List serial ports and exit")
    parser.add_argument("--fleet-port", type=int, default=DEFAULT_FLEET_PORT, help=f"Fleet mode HTTP port (default {DEFAULT_FLEET_PORT})")
    parser.add_argument("--rift-host", type=str, default="127.0.0.1", help="Fleet mode: RIFT/NORA fleet-registry host (default 127.0.0.1)")
    parser.add_argument("--rift-port", type=int, default=5000, help="Fleet mode: RIFT/NORA fleet-registry port (default 5000)")
    parser.add_argument("--connect", type=str, default=None, metavar="URL", help="Client mode: no serial port; mirror and control another controller's arm, e.g. --connect http://192.168.0.10:5011")
    parser.add_argument("--serve", action="store_true", help="Start the HTTP server (web page + RIFT API) in any mode - the default now, kept for old launchers")
    parser.add_argument("--no-serve", action="store_true", help="Don't start the HTTP server or join RIFT unless you pick Fleet mode")
    parser.add_argument("--no-register", action="store_true", help="Fleet mode: don't heartbeat to the fleet registry, just serve the HTTP API")
    parser.add_argument("--ladder", action="store_true",
                    help="join / host the fleet's WiFi (fleet_ladder.py; FLEET_LADDER=1 does the same)")
    parser.add_argument("--camera", type=int, default=0, help="Mind mode: the webcam that watches the arm (default 0)")
    args = parser.parse_args()
    global LADDER
    from fleet_ladder import FleetLadder   # the fleet's WiFi ladder (fleet TODO, section 2)
    LADDER = FleetLadder("ARMCTL", enabled=args.ladder or None).start()
    if args.connect and (args.serve or args.mode == "fleet"):
        parser.error("--connect can't be combined with --serve or --mode fleet (this controller has no arm of its own)")
    # Like every other robot, ARM joins RIFT and serves its web page whenever
    # it runs (a client mirroring another arm has nothing of its own to serve).
    if not args.connect and not args.no_serve:
        args.serve = True

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
    js = pick_joystick(args.device)   # a joystick first, else a gamepad; picked again when one is plugged in / out
    if js is None:
        print("No joystick or gamepad yet - plug one in any time for Joystick mode.")

    port = None if args.connect else (args.port or autodetect_port())
    ser = None
    if port:
        try:
            ser = serial.Serial(port, args.baud, timeout=1)
            time.sleep(2)  # give the Arduino time to reset after the serial connection opens
            status = f"Connected to {port} @ {args.baud} baud."
        except serial.SerialException as e:
            status = f"Could not open {port}: {e}"
    elif args.connect:
        status = f"Remote arm at {args.connect} (no local serial port)."
    else:
        status = "No Arduino-like serial port found - display-only mode."
    print(status)

    screen = pygame.display.set_mode((WINDOW_WIDTH + PANEL_W, WINDOW_HEIGHT))
    pygame.display.set_caption("Arm Controller")
    try:  # window icon: the robot's avatar
        pygame.display.set_icon(pygame.image.load(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "images", "arm-icon.png")))
    except (pygame.error, OSError):
        pass
    pygame.key.set_repeat(KEY_REPEAT_DELAY_MS, KEY_REPEAT_INTERVAL_MS)
    font = pygame.font.SysFont(None, 24)
    small_font = pygame.font.SysFont(None, 18)
    avatar = round_avatar(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "images", "arm_avatar.jpg"), 44)
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

    fleet_lan_ip = local_lan_ip()

    fleet_lock = threading.Lock()
    fleet_state = {"angles": {n: motors[n]["rest"] for n in motors}}
    fleet_status = {"started": False, "error": None}

    def ensure_fleet_started():
        if args.connect:
            return  # client mode has no arm of its own to serve
        start_fleet_server(args, motors, fleet_state, fleet_lock, lambda: ser is not None, fleet_status)

    if mode == "fleet" or args.serve:
        ensure_fleet_started()
        if fleet_status["error"]:
            print(fleet_status["error"])
        elif mode != "fleet":
            status += f"  |  Web: http://{fleet_lan_ip}:{args.fleet_port}"
            print(f"Web control on http://{fleet_lan_ip}:{args.fleet_port}")

    channel_to_motor = {m["channel"]: n for n, m in motors.items()}
    prev_local = {}
    last_mode = mode

    remote = RemoteArm(args.connect, fleet_state["angles"], fleet_lock) if args.connect else None
    adopted = remote is None  # a client waits for the hub's real angles before its own inputs may write

    def follow_sliders():
        """Slider positions adopt the shared angles (so web/other-input changes show up)."""
        with fleet_lock:
            for sl, n in zip(slider_mode_sliders, sorted(motors)):
                sl.angle = fleet_state["angles"][n]
                prev_local[n] = sl.angle

    mode_buttons = {
        "joystick": Button((20, MODE_BUTTON_Y, 98, 34), "Joystick"),
        "slider": Button((124, MODE_BUTTON_Y, 98, 34), "Sliders"),
        "ik": Button((228, MODE_BUTTON_Y, 98, 34), "IK"),
        "fleet": Button((332, MODE_BUTTON_Y, 98, 34), "Fleet"),
        "mind": Button((436, MODE_BUTTON_Y, 98, 34), "Mind"),
    }

    # Her mind: only where it can run (mind.can_think(): an x86 PC with a GPU), with her camera
    eyes = ArmEyes(args.camera)
    mind_state = {"capable": False, "why": "checking this PC..."}

    def check_mind():
        mind_state["capable"], mind_state["why"] = mind.can_think()
    threading.Thread(target=check_mind, daemon=True).start()
    record_button = Button((30, TRANSPORT_BUTTON_Y, 160, 30), "Record")
    theme_button = Button((WINDOW_WIDTH + 10, 12, 150, 30), f"THEME: {SETTINGS.theme}")
    voice = kit.Voice(ARM_VOICE[0], ARM_LINES, ARM_VOICE[1], ARM_VOICE[2])
    voice.on = SETTINGS.get("voice", True)
    voice_button = Button((WINDOW_WIDTH + 170, 12, 150, 30), "VOICE ON" if voice.on else "VOICE OFF")
    heard = {"mode": None, "recording": False, "playing": False, "claw": None, "started": False}
    play_button = Button((200, TRANSPORT_BUTTON_Y, 160, 30), "Play")
    stick = StickDriver(hold=not args.stick_rest)
    hold_box = TickBox((20, MARGIN_TOP + 6 * 28 + 12), "Hold position (unticked: back to rest when you let go)",
                       stick.hold)
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

    def set_shared(changed):
        """Write {motor: angle} into the shared angles (and to the hub, as a client)."""
        with fleet_lock:
            fleet_state["angles"].update(changed)
        if remote is not None:
            remote.queue(changed)

    def step_motor(n, direction, deg):
        """Move motor n by deg in direction +1/-1 (before invert), within its limits."""
        m = motors[n]
        if m["invert"]:
            direction = -direction
        with fleet_lock:
            angle = max(m["min"], min(m["max"], fleet_state["angles"][n] + direction * deg))
        set_shared({n: angle})

    def set_claw(closed):
        if motors[6]["invert"]:
            closed = not closed
        set_shared({6: motors[6]["max"] if closed else motors[6]["min"]})

    def macro_row_rect(i):
        return pygame.Rect(30, MACRO_LIST_Y + i * MACRO_ROW_H, 500, MACRO_ROW_H)

    # what she picks up (Mind mode): a colour, or a thing you type
    target = {"kind": "colour", "name": "red", "hue": 0}
    text_box = {"focus": False, "text": ""}
    mind_hits = {"colours": [], "text": None, "preview": None}

    def set_target(**t):
        target.clear()
        target.update(t)
        arm_mind.goal = pick_goal(target)   # she picks it up from her next thought on

    look, act, seen = arm_body(eyes, motors, fleet_state, fleet_lock, step_motor, set_claw, set_shared, target)
    arm_mind = mind.Mind("ARM", ARM_PERSONA, ARM_MOVES, look, act, voice=ARM_VOICE[0], rate=ARM_VOICE[1],
                         pitch=ARM_VOICE[2], safety=ARM_SAFETY)

    running = True
    try:
        while running:
            for event in pygame.event.get():
                # typing what to pick up: the text box has the keys while it's focused
                if text_box["focus"] and event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_RETURN:
                        text_box["focus"] = False
                        if text_box["text"].strip():
                            set_target(kind="thing", name=text_box["text"].strip())
                    elif event.key == pygame.K_ESCAPE:
                        text_box["focus"] = False
                    elif event.key == pygame.K_BACKSPACE:
                        text_box["text"] = text_box["text"][:-1]
                    elif event.unicode and event.unicode.isprintable() and len(text_box["text"]) < 40:
                        text_box["text"] += event.unicode
                    continue
                if event.type == pygame.MOUSEMOTION and event.buttons[0] and event.pos[0] > WINDOW_WIDTH and event.pos[1] > WINDOW_HEIGHT - 300:
                    ORBIT[0] += event.rel[0] * 0.01                                       # drag her 3D view round
                    ORBIT[1] = max(0.0, min(math.pi / 2, ORBIT[1] + event.rel[1] * 0.01))
                if mode == "mind" and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    pos = event.pos
                    picked = next(((n, h) for r, n, h in mind_hits["colours"] if r.collidepoint(pos)), None)
                    if picked:
                        set_target(kind="colour", name=picked[0], hue=picked[1])
                        text_box["focus"] = False
                        continue
                    if mind_hits["text"] and mind_hits["text"].collidepoint(pos):
                        text_box["focus"] = True
                        continue
                    if mind_hits["preview"] and mind_hits["preview"].collidepoint(pos):
                        frame = eyes.latest()   # that pixel's colour becomes the target
                        if frame is not None:
                            fh, fw = frame.shape[:2]
                            fx = (pos[0] - mind_hits["preview"].x) * fw // PREVIEW_W
                            fy = (pos[1] - mind_hits["preview"].y) * fh // PREVIEW_H
                            hue, sat = hue_at(frame, fx, fy)
                            if sat >= SAT_MIN:
                                set_target(kind="colour", name=f"picked (hue {hue})", hue=hue)
                            else:
                                status = "That spot is too grey to follow by colour - pick something more colourful."
                        continue
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running = False
                elif event.type in (pygame.JOYDEVICEADDED, pygame.JOYDEVICEREMOVED):
                    if js is not None:
                        js.quit()
                    js = pick_joystick(args.device)   # the joystick wins over a gamepad
                    if js is None and mode == "joystick":
                        mode = "slider"
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_F1:
                    import keymap   # scripts/keymap.py: every key and joystick input, in its own window
                    keymap.open_window()
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
                        elif mode_buttons["mind"].hit(pos) and mind_state["capable"]:
                            mode = "mind"
                        elif theme_button.hit(pos):
                            apply_theme_colours = SETTINGS.next_theme()
                            apply_theme(SETTINGS.theme, SETTINGS.get("custom"))
                            theme_button.label = f"THEME: {SETTINGS.theme}"
                        elif voice_button.hit(pos):
                            voice.on = not voice.on
                            SETTINGS["voice"] = voice.on
                            SETTINGS.save()
                            voice_button.label = "VOICE ON" if voice.on else "VOICE OFF"
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
                        elif mode == "joystick" and js is not None and hold_box.hit(pos):
                            hold_box.checked = not hold_box.checked
                            stick.set_hold(hold_box.checked)
                        elif mode == "ik" and elbow_toggle.hit(pos):
                            elbow_down = not elbow_down
                        elif mode == "ik" and claw_toggle.hit(pos):
                            claw_closed = not claw_closed
                        else:
                            for i in range(min(len(macros), MACRO_LIST_MAX)):
                                if macro_row_rect(i).collidepoint(pos):
                                    selected_macro_index = i

                if not playing and mode != "ik" and adopted:
                    if event.type == pygame.KEYDOWN and event.key in KEY_STEPS:
                        n, direction = KEY_STEPS[event.key]
                        fine = event.mod & pygame.KMOD_SHIFT
                        step_motor(n, direction, KEY_FINE_STEP_DEG if fine else KEY_STEP_DEG)
                    elif event.type in (pygame.KEYDOWN, pygame.KEYUP) and event.key == KEY_CLAW:
                        set_claw(event.type == pygame.KEYDOWN)
                    elif event.type == pygame.KEYDOWN and event.key == KEY_REST:
                        set_shared({n: motors[n]["rest"] for n in motors})

                if not playing:
                    if mode == "joystick" and js is not None and adopted:
                        step = joystick_step(event)
                        if step is not None:
                            step_motor(*step, BUTTON_STEP_DEG)
                    elif mode == "slider":
                        for s in slider_mode_sliders:
                            s.handle_event(event)
                    elif mode == "ik":
                        for s in ik_sliders.values():
                            s.handle_event(event)

            # ---- her mind thinks only in Mind mode, and never while a macro plays ----
            if mode == "mind":
                eyes.start()        # the camera runs while Mind mode is open (preview, colour finder)
            elif eyes._running:
                eyes.close()
            want_mind = mode == "mind" and not playing and adopted and mind_state["capable"]
            if want_mind and not arm_mind.on:
                arm_mind.start(goal=pick_goal(target))
            elif not want_mind and arm_mind.on:
                arm_mind.stop()

            # ---- compute + send this frame's commands ----
            if playing:
                elapsed = time.time() - play_start
                while play_index < len(play_steps) and play_steps[play_index]["t"] <= elapsed:
                    commands = {int(ch): ang for ch, ang in play_steps[play_index]["commands"].items()}
                    last_sent = send(ser, commands, last_sent)
                    send_talk(ser, fleet_state, fleet_lock)
                    changed = {channel_to_motor[ch]: ang for ch, ang in commands.items() if ch in channel_to_motor}
                    with fleet_lock:
                        fleet_state["angles"].update(changed)
                    if remote is not None:
                        remote.queue(changed)
                    play_index += 1
                last_sent = send(ser, last_sent, last_sent)  # keepalive between macro steps
                if mode == "slider":
                    follow_sliders()
                if play_index >= len(play_steps):
                    playing = False
                    mode = play_prev_mode
            else:
                if mode != last_mode:
                    prev_local.clear()
                    if mode == "slider":
                        follow_sliders()
                    last_mode = mode

                local_commands = None  # channel -> angle from this mode's own input, if any
                if mode == "joystick" and js is not None:
                    with fleet_lock:
                        now_angles = dict(fleet_state["angles"])
                    local_commands = stick.update(js, motors, now_angles)
                elif mode == "slider":
                    local_commands = {s.channel: s.angle for s in slider_mode_sliders}
                elif mode == "ik":
                    if geometry_ready(geometry):
                        sol = inverse_kinematics(
                            motors, geometry,
                            ik_sliders["x"].angle, ik_sliders["y"].angle, ik_sliders["z"].angle,
                            pitch_deg=ik_sliders["pitch"].angle, elbow_down=elbow_down,
                        )
                        if sol is not None:
                            ik_reachable = True
                            local_commands = {motors[n]["channel"]: a for n, a in sol.items()}
                            local_commands[motors[5]["channel"]] = ik_sliders["roll"].angle
                            local_commands[motors[6]["channel"]] = motors[6]["max"] if claw_closed else motors[6]["min"]
                            last_valid_ik_commands = local_commands
                        else:
                            ik_reachable = False
                            local_commands = last_valid_ik_commands  # hold last good pose

                # Every mode shares one set of angles with the web page / RIFT: inputs that
                # changed write into it, the rest follow it (see merge_local).
                if local_commands is not None:
                    local = {channel_to_motor[ch]: a for ch, a in local_commands.items() if ch in channel_to_motor}
                    if not adopted:
                        if remote.synced:  # connected: take the hub's state as-is, don't move the arm
                            prev_local.clear()
                            prev_local.update(local)
                            adopted = True
                    else:
                        changed = merge_local(local, prev_local, fleet_state["angles"], fleet_lock)
                        if remote is not None and changed:
                            remote.queue(changed)
                    if mode == "slider":
                        follow_sliders()
                with fleet_lock:
                    commands = {motors[n]["channel"]: fleet_state["angles"][n] for n in motors}

                last_sent = send(ser, commands, last_sent)
                send_talk(ser, fleet_state, fleet_lock)
                if recording:
                    record_steps.append({
                        "t": time.time() - record_start,
                        "commands": {str(ch): ang for ch, ang in commands.items()},
                    })

            if remote is not None:
                status = f"Remote arm {args.connect}: " + ("connected" if remote.connected else "UNREACHABLE")

            # ---- draw ----
            screen.fill(BG_COLOR)
            screen.blit(font.render("Arm Controller", True, TEXT_COLOR), (20, 16))
            if avatar:
                screen.blit(avatar, (WINDOW_WIDTH - 20 - 44, 6))
            screen.blit(small_font.render(status, True, STATUS_COLOR), (20, 40))

            for name, btn in mode_buttons.items():
                enabled = name != "joystick" or js is not None
                btn.draw(screen, font, active=(mode == name), color=(None if enabled else BUTTON_DISABLED_COLOR))

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
                if js is not None:
                    hold_box.draw(screen, small_font)
            elif mode == "fleet":
                if fleet_status["error"]:
                    screen.blit(small_font.render(fleet_status["error"], True, WARN_COLOR), (20, MARGIN_TOP - 20))
                else:
                    screen.blit(small_font.render(
                        f"Open http://{fleet_lan_ip}:{args.fleet_port} in a browser to control"
                        + ("" if args.no_register else f"  -  heartbeating to RIFT at {args.rift_host}:{args.rift_port}"),
                        True, STATUS_COLOR), (20, MARGIN_TOP - 20))
                    y = MARGIN_TOP
                    for n, m in sorted(motors.items()):
                        with fleet_lock:
                            ang = fleet_state["angles"][n]
                        screen.blit(font.render(f"Motor {n} (ch {m['channel']}): {ang}", True, TEXT_COLOR), (20, y))
                        y += 28

            elif mode == "mind":
                mind_hits = draw_mind(screen, font, small_font, arm_mind, seen, eyes, mind_state, target, text_box)

            if playing:
                screen.blit(small_font.render(f"Playing... step {play_index}/{len(play_steps)}", True, STATUS_COLOR),
                            (370, TRANSPORT_BUTTON_Y + 8))

            # the arm panel: her arm from her geometry (her emulator when no Arduino's plugged in)
            with fleet_lock:
                now_angles = {int(k): v for k, v in fleet_state["angles"].items()}
            draw_arm(screen, font, small_font, motors, geometry, now_angles, WINDOW_WIDTH)
            theme_button.draw(screen, small_font)
            voice_button.draw(screen, small_font, active=voice.on)
            if voice.on and voice.said:
                screen.blit(small_font.render(kit.fit(f'ARM: "{voice.said}"', small_font, PANEL_W - 30), True, TEXT_COLOR),
                            (WINDOW_WIDTH + 20, WINDOW_HEIGHT - 30))

            # her voice, from what changed (her MIND talks for itself)
            if not arm_mind.on:
                if not heard["started"]:
                    heard["started"] = True
                    voice.say("remote" if args.connect else "connect" if ser is not None else "display")
                if heard["mode"] is not None and mode != heard["mode"] and mode != "mind":
                    voice.say("mode_" + mode)
                if recording != heard["recording"]:
                    voice.say("record_on" if recording else "record_off")
                if playing != heard["playing"]:
                    voice.say("play" if playing else "stop")
                if heard["claw"] is not None and claw_closed != heard["claw"]:
                    voice.say("claw_close" if claw_closed else "claw_open")
            heard.update(mode=mode, recording=recording, playing=playing, claw=claw_closed)

            pygame.display.flip()
            clock.tick(args.rate if args.rate > 0 else 30)
    finally:
        if arm_mind.on:
            arm_mind.stop()
        eyes.close()
        if remote is not None:
            remote.close()
        if ser is not None:
            ser.close()
        if js is not None:
            js.quit()
        pygame.joystick.quit()
        pygame.quit()


if __name__ == "__main__":
    main()
