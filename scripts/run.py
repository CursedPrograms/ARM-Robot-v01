#!/usr/bin/env python3
"""
run.py - Read joystick/flight-stick input and drive servos on an Arduino
(running the matching .ino sketch) over USB serial.

Mapping (edit AXIS_*/BUTTON_TRIGGER below to match your controller):
    Servo 0  <- main stick LEFT / RIGHT   (base rotation)
    Servo 1  <- main stick FORWARD / BACK (shoulder)
    Servo 2  <- small joystick (elbow)
    Servo 5  <- trigger button (claw open/close)

Requires:
    pip install pygame pyserial

Usage:
    python run.py --list                  # list joysticks
    python run.py --list-ports             # list serial ports
    python run.py --port /dev/ttyUSB0      # (Linux/Mac) or COM5 (Windows)
    python run.py --port COM5 --device 0 --rate 30
"""

import argparse
import sys
import time

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


# ----------------------------------------------------------------------
# CONFIG - adjust these indices/ranges to match your physical controller
# ----------------------------------------------------------------------

# Main stick axes (base rotation + shoulder)
AXIS_BASE = 0          # left/right  -> servo 0
AXIS_SHOULDER = 1       # forward/back -> servo 1

# Small joystick axis (elbow). Many HOTAS sticks expose this as axis 2 or 3 -
# run with --list-axes while wiggling it to confirm the index on your device.
AXIS_ELBOW = 2

# Trigger button (claw)
BUTTON_TRIGGER = 0

# Servo angle ranges (degrees), matching SERVOMIN/SERVOMAX in the .ino sketch
BASE_MIN, BASE_MAX = 0, 270
SHOULDER_MIN, SHOULDER_MAX = 0, 270
ELBOW_MIN, ELBOW_MAX = 30, 170      # matches "170 //30 Min" comment in sketch

CLAW_OPEN_ANGLE = 25
CLAW_CLOSED_ANGLE = 100

# Servo channel indices on the PCA9685 (must match the .ino sketch)
SERVO_BASE = 0
SERVO_SHOULDER = 1
SERVO_ELBOW = 2
SERVO_CLAW = 5

# Deadzone for stick axes to avoid jitter near center
DEADZONE = 0.05


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


def list_axes_live(js):
    """Print live axis values so you can identify which index is which stick."""
    print("Wiggle each axis to identify its index. Ctrl+C to stop.\n")
    try:
        while True:
            pygame.event.pump()
            vals = " ".join(f"A{i}:{js.get_axis(i):+.2f}" for i in range(js.get_numaxes()))
            print(vals, end="\r", flush=True)
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nDone.")


def main():
    parser = argparse.ArgumentParser(description="Joystick -> Arduino servo controller over USB serial.")
    parser.add_argument("--device", type=int, default=0, help="Joystick index to use (default 0)")
    parser.add_argument("--port", type=str, default=None, help="Serial port, e.g. COM5 or /dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baud rate (default 115200, must match .ino)")
    parser.add_argument("--rate", type=float, default=20, help="Update rate in Hz (default 20)")
    parser.add_argument("--list", action="store_true", help="List joystick devices and exit")
    parser.add_argument("--list-ports", action="store_true", help="List serial ports and exit")
    parser.add_argument("--list-axes", action="store_true", help="Live-print axis values to help mapping, then exit")
    args = parser.parse_args()

    if args.list:
        list_joysticks()
        return

    if args.list_ports:
        list_serial_ports()
        return

    pygame.init()
    pygame.joystick.init()

    count = pygame.joystick.get_count()
    if count == 0:
        print("No joystick/controller devices found. Plug one in and try again.")
        return
    if args.device >= count:
        print(f"Device index {args.device} out of range (only {count} found). Run --list to see options.")
        return

    js = pygame.joystick.Joystick(args.device)
    js.init()
    print(f"Using joystick: {js.get_name()}")

    if args.list_axes:
        list_axes_live(js)
        return

    if not args.port:
        print("No --port specified. Use --list-ports to find your Arduino's serial port.")
        return

    try:
        ser = serial.Serial(args.port, args.baud, timeout=1)
    except serial.SerialException as e:
        print(f"Could not open serial port {args.port}: {e}")
        return

    # Give the Arduino time to reset after the serial connection opens
    time.sleep(2)
    print(f"Connected to {args.port} @ {args.baud} baud.")
    print("Sending servo commands. Press Ctrl+C to stop.\n")

    interval = 1.0 / args.rate if args.rate > 0 else 0.05
    claw_closed = False
    prev_trigger = False
    last_sent = {}

    try:
        while True:
            pygame.event.pump()

            base_val = js.get_axis(AXIS_BASE) if js.get_numaxes() > AXIS_BASE else 0.0
            shoulder_val = js.get_axis(AXIS_SHOULDER) if js.get_numaxes() > AXIS_SHOULDER else 0.0
            elbow_val = js.get_axis(AXIS_ELBOW) if js.get_numaxes() > AXIS_ELBOW else 0.0
            trigger = bool(js.get_button(BUTTON_TRIGGER)) if js.get_numbuttons() > BUTTON_TRIGGER else False

            base_angle = axis_to_angle(base_val, BASE_MIN, BASE_MAX)
            shoulder_angle = axis_to_angle(shoulder_val, SHOULDER_MIN, SHOULDER_MAX)
            elbow_angle = axis_to_angle(elbow_val, ELBOW_MIN, ELBOW_MAX)

            # Toggle claw on trigger press (rising edge)
            if trigger and not prev_trigger:
                claw_closed = not claw_closed
            prev_trigger = trigger
            claw_angle = CLAW_CLOSED_ANGLE if claw_closed else CLAW_OPEN_ANGLE

            commands = {
                SERVO_BASE: base_angle,
                SERVO_SHOULDER: shoulder_angle,
                SERVO_ELBOW: elbow_angle,
                SERVO_CLAW: claw_angle,
            }

            # Only send a line if something changed, to keep serial traffic light
            if commands != last_sent:
                line = ",".join(f"{ch}:{ang}" for ch, ang in commands.items())
                ser.write((line + "\n").encode("ascii"))
                last_sent = commands

            print(f"base:{base_angle:3d} shoulder:{shoulder_angle:3d} "
                  f"elbow:{elbow_angle:3d} claw:{'closed' if claw_closed else 'open':6s}", end="\r", flush=True)

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        ser.close()
        js.quit()
        pygame.joystick.quit()
        pygame.quit()


if __name__ == "__main__":
    main()
