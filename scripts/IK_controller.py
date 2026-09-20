#!/usr/bin/env python3
"""
IK_controller.py - Inverse/forward kinematics for the arm, driving motors
1-4 (base, shoulder, elbow, wrist pitch) to reach a target (x, y, z)
position over USB serial, talking to the Arduino running scripts/arm/arm.ino.

Physical role of each motor (see scripts/config.json / motor_config.py for
channel/range/rest/invert):
    Motor 1 - base rotation (yaw, about the vertical axis)
    Motor 2 - shoulder (pitch)
    Motor 3 - elbow (pitch)
    Motor 4 - wrist pitch
    Motor 5 - wrist roll (NOT part of position IK - set directly)
    Motor 6 - claw open/close (NOT part of position IK - set directly)

Coordinate frame (millimetres):
    Origin is the base rotation axis at the mounting surface.
    +Z is up. X/Y are horizontal; the arm's shoulder/elbow/wrist all move
    in the single vertical plane selected by the base's yaw rotation.

This script needs scripts/config.json's "geometry" section filled in
(baseHeight, upperArmLength, forearmLength, wristLength, all in mm) before
it can compute anything real - those are 0 placeholders until measured.
Each motor's "kinematicSign" (1 or -1) says whether increasing that
motor's raw servo angle increases the physical joint angle away from its
"rest" position - also needs checking once the arm can be watched move.

Requires:
    pip install pyserial

Usage:
    python IK_controller.py --list-ports                  # find the Arduino's port
    python IK_controller.py --fk --base 135 --shoulder 135 --elbow 135 --wrist 135
    python IK_controller.py --port COM6 --x 150 --y 0 --z 100
    python IK_controller.py --port COM6 --x 150 --y 0 --z 100 --pitch 0 --elbow-down
    python IK_controller.py --port COM6 --x 150 --y 0 --z 100 --dry-run
"""

import argparse
import math
import sys
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("pyserial is not installed. Install it with: pip install pyserial")
    sys.exit(1)

from motor_config import load_motor_config, load_geometry

# Descriptions that identify likely Arduino USB-serial adapters, for --port auto-detect
ARDUINO_HINTS = ("arduino", "ch340", "usb-serial", "usb serial", "cp210", "ftdi")


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


def check_geometry(geometry):
    """Refuse to do IK/FK math against unmeasured (zero-length) geometry."""
    missing = [k for k in ("upperArmLength", "forearmLength") if geometry.get(k, 0) == 0]
    if missing:
        print(f"Geometry not measured yet: {', '.join(missing)} are 0 in scripts/config.json's "
              f"\"geometry\" section. Measure the arm and fill those in before using IK/FK.")
        return False
    return True


def raw_to_deg(motors, n, raw_angle):
    """Convert a motor's raw servo angle to a kinematic joint angle (degrees),
    relative to its configured resting position."""
    m = motors[n]
    return (raw_angle - m["rest"]) * m["kinematicSign"]


def deg_to_raw(motors, n, joint_deg):
    """Convert a kinematic joint angle (degrees) to a motor's raw servo angle,
    clamped to its configured range. Returns (raw_angle, in_range)."""
    m = motors[n]
    raw = m["rest"] + joint_deg * m["kinematicSign"]
    clamped = max(m["min"], min(m["max"], raw))
    return int(round(clamped)), (m["min"] <= raw <= m["max"])


def forward_kinematics(motors, geometry, base_raw, shoulder_raw, elbow_raw, wrist_raw):
    """Raw servo angles (motors 1-4) -> (x, y, z) tip position in mm."""
    base = math.radians(raw_to_deg(motors, 1, base_raw))
    shoulder = math.radians(raw_to_deg(motors, 2, shoulder_raw))
    elbow = math.radians(raw_to_deg(motors, 3, elbow_raw))
    wrist = math.radians(raw_to_deg(motors, 4, wrist_raw))

    l1 = geometry["upperArmLength"]
    l2 = geometry["forearmLength"]
    l3 = geometry["wristLength"]

    # Position in the vertical plane before applying base yaw.
    r = l1 * math.cos(shoulder) + l2 * math.cos(shoulder + elbow) + l3 * math.cos(shoulder + elbow + wrist)
    z = geometry["baseHeight"] + \
        l1 * math.sin(shoulder) + l2 * math.sin(shoulder + elbow) + l3 * math.sin(shoulder + elbow + wrist)

    x = r * math.cos(base)
    y = r * math.sin(base)
    return x, y, z


def inverse_kinematics(motors, geometry, x, y, z, pitch_deg=0.0, elbow_down=False):
    """Target (x, y, z) mm + desired end-effector pitch (deg, 0 = level) ->
    raw servo angles for motors 1-4, or None if unreachable."""
    l1 = geometry["upperArmLength"]
    l2 = geometry["forearmLength"]
    l3 = geometry["wristLength"]

    base_deg = math.degrees(math.atan2(y, x))
    r = math.hypot(x, y)
    z_rel = z - geometry["baseHeight"]

    pitch = math.radians(pitch_deg)
    # Wrist-joint position: back off from the target tip by the wrist link,
    # along the desired approach direction.
    r_w = r - l3 * math.cos(pitch)
    z_w = z_rel - l3 * math.sin(pitch)

    dist2 = r_w * r_w + z_w * z_w
    cos_elbow = (dist2 - l1 * l1 - l2 * l2) / (2 * l1 * l2)
    if not -1.0 <= cos_elbow <= 1.0:
        return None  # target out of reach

    elbow_mag = math.acos(cos_elbow)
    elbow = -elbow_mag if elbow_down else elbow_mag

    shoulder = math.atan2(z_w, r_w) - math.atan2(l2 * math.sin(elbow), l1 + l2 * math.cos(elbow))
    wrist = pitch - shoulder - elbow

    base_raw, base_ok = deg_to_raw(motors, 1, base_deg)
    shoulder_raw, shoulder_ok = deg_to_raw(motors, 2, math.degrees(shoulder))
    elbow_raw, elbow_ok = deg_to_raw(motors, 3, math.degrees(elbow))
    wrist_raw, wrist_ok = deg_to_raw(motors, 4, math.degrees(wrist))

    if not (base_ok and shoulder_ok and elbow_ok and wrist_ok):
        return None  # solvable geometrically, but outside this arm's servo ranges

    return {1: base_raw, 2: shoulder_raw, 3: elbow_raw, 4: wrist_raw}


def main():
    parser = argparse.ArgumentParser(description="Inverse/forward kinematics controller for the arm, over USB serial.")
    parser.add_argument("--port", type=str, default=None, help="Serial port, e.g. COM6 (auto-detected if omitted)")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baud rate (default 115200, must match .ino)")
    parser.add_argument("--list-ports", action="store_true", help="List serial ports and exit")

    parser.add_argument("--fk", action="store_true", help="Forward-kinematics mode: print tip (x,y,z) for --base/--shoulder/--elbow/--wrist raw angles")
    parser.add_argument("--base", type=float, help="Motor 1 raw servo angle (FK mode)")
    parser.add_argument("--shoulder", type=float, help="Motor 2 raw servo angle (FK mode)")
    parser.add_argument("--elbow", type=float, help="Motor 3 raw servo angle (FK mode)")
    parser.add_argument("--wrist", type=float, help="Motor 4 raw servo angle (FK mode)")

    parser.add_argument("--x", type=float, help="Target X (mm), IK mode")
    parser.add_argument("--y", type=float, help="Target Y (mm), IK mode")
    parser.add_argument("--z", type=float, help="Target Z (mm), IK mode")
    parser.add_argument("--pitch", type=float, default=0.0, help="Desired end-effector pitch in degrees, 0 = level (default 0)")
    parser.add_argument("--elbow-down", action="store_true", help="Use the elbow-down solution instead of elbow-up")

    parser.add_argument("--roll", type=int, help="Motor 5 (wrist roll) raw servo angle to also send")
    parser.add_argument("--claw", choices=["open", "closed"], help="Motor 6 (claw) position to also send")

    parser.add_argument("--dry-run", action="store_true", help="Compute and print only, don't open serial or send anything")
    args = parser.parse_args()

    if args.list_ports:
        list_serial_ports()
        return

    motors = load_motor_config()
    geometry = load_geometry()

    if args.fk:
        if None in (args.base, args.shoulder, args.elbow, args.wrist):
            print("--fk requires --base --shoulder --elbow --wrist (raw servo angles).")
            return
        if not check_geometry(geometry):
            return
        x, y, z = forward_kinematics(motors, geometry, args.base, args.shoulder, args.elbow, args.wrist)
        print(f"Tip position: x={x:.1f} y={y:.1f} z={z:.1f} mm")
        return

    if None in (args.x, args.y, args.z):
        print("Specify --x --y --z (IK mode), or use --fk. --list-ports to find the Arduino's port.")
        return

    if not check_geometry(geometry):
        return

    commands = inverse_kinematics(motors, geometry, args.x, args.y, args.z, args.pitch, args.elbow_down)
    if commands is None:
        print(f"Target ({args.x}, {args.y}, {args.z}) mm is not reachable with the current geometry/servo ranges.")
        return

    if args.roll is not None:
        commands[5] = max(motors[5]["min"], min(motors[5]["max"], args.roll))
    if args.claw is not None:
        commands[6] = motors[6]["max"] if args.claw == "closed" else motors[6]["min"]

    channel_commands = {motors[n]["channel"]: angle for n, angle in commands.items()}
    print("Solved: " + " ".join(f"motor{n}:{angle}" for n, angle in sorted(commands.items())))

    if args.dry_run:
        return

    port = args.port or autodetect_port()
    if not port:
        print("No --port specified and no Arduino-like serial port found. Use --list-ports to see options.")
        return

    try:
        ser = serial.Serial(port, args.baud, timeout=1)
    except serial.SerialException as e:
        print(f"Could not open serial port {port}: {e}")
        return

    time.sleep(2)  # give the Arduino time to reset after the serial connection opens
    line = ",".join(f"{ch}:{ang}" for ch, ang in channel_commands.items())
    ser.write((line + "\n").encode("ascii"))
    print(f"Sent to {port}: {line}")
    ser.close()


if __name__ == "__main__":
    main()
