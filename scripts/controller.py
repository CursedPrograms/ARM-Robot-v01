#!/usr/bin/env python3
"""
controller.py - Drive motor 1-4 from a joystick over USB serial,
talking to the Arduino running scripts/arm/arm.ino.

Mapping:
    Axis 0 (A0) -> Motor 1 / servo channel 0 (base)
        -1.00 = left, 0.00 = centre, +1.00 = right
    Axis 1 (A1) -> Motor 2 / servo channel 1 (shoulder)
        -1.00 = left, 0.00 = centre, +1.00 = right
    Hat 0 Y (D-pad up/down) -> Motor 3 / servo channel 2 (elbow)
        +1 = forward, 0 = centre, -1 = backward
    Buttons 2/3 -> Motor 4 / servo channel 3 (wrist)
        B3=1,B2=0 = forward, B2=1,B3=0 = backward, otherwise = centre

Requires:
    pip install pygame pyserial

Usage:
    python controller.py --list-ports          # find your Arduino's port
    python controller.py --port COM6
    python controller.py --port COM6 --device 0 --rate 30
"""

import argparse
import json
import sys
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


# Joystick axes
AXIS_MOTOR1 = 0
AXIS_MOTOR2 = 1

# Joystick hat (D-pad) used for motor 3: hat index and its Y-component
HAT_MOTOR3 = 0
HAT_MOTOR3_COMPONENT = 1

# Joystick buttons used for motor 4 (forward/backward pair, no centre button)
BUTTON_MOTOR4_BACKWARD = 2
BUTTON_MOTOR4_FORWARD = 3

# Servo channel indices on the PCA9685 (must match scripts/arm/arm.ino)
SERVO_MOTOR1 = 0
SERVO_MOTOR2 = 1
SERVO_MOTOR3 = 2
SERVO_MOTOR4 = 3

# Servo angle range (degrees), matching SERVOMIN/SERVOMAX in arm.ino.
# -1.00 -> MIN (left), 0.00 -> centre, +1.00 -> MAX (right)
ANGLE_MIN, ANGLE_MAX = 0, 270

# Motor 4 is mechanically limited to a narrower range than the other motors.
MOTOR4_ANGLE_MIN, MOTOR4_ANGLE_MAX = 65, 205

# Deadzone for stick axes to avoid jitter near center
DEADZONE = 0.05

# Descriptions that identify likely Arduino USB-serial adapters, for --port auto-detect
ARDUINO_HINTS = ("arduino", "ch340", "usb-serial", "usb serial", "cp210", "ftdi")

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


def load_config():
    """Load invertMotor1..4 (and other settings) from config.json, if present."""
    defaults = {
        "invertMotor1": False,
        "invertMotor2": False,
        "invertMotor3": False,
        "invertMotor4": False,
    }
    if not CONFIG_PATH.exists():
        return defaults
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"Warning: could not read {CONFIG_PATH.name} ({e}), using defaults.")
        return defaults
    defaults.update(data)
    return defaults


def axis_to_angle(value, lo=ANGLE_MIN, hi=ANGLE_MAX, deadzone=DEADZONE):
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


def main():
    parser = argparse.ArgumentParser(description="Joystick -> Arduino motor controller over USB serial.")
    parser.add_argument("--device", type=int, default=0, help="Joystick index to use (default 0)")
    parser.add_argument("--port", type=str, default=None, help="Serial port, e.g. COM6 or /dev/ttyUSB0 (auto-detected if omitted)")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baud rate (default 115200, must match .ino)")
    parser.add_argument("--rate", type=float, default=20, help="Update rate in Hz (default 20)")
    parser.add_argument("--list", action="store_true", help="List joystick devices and exit")
    parser.add_argument("--list-ports", action="store_true", help="List serial ports and exit")
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

    config = load_config()
    invert_motor1 = bool(config.get("invertMotor1", False))
    invert_motor2 = bool(config.get("invertMotor2", False))
    invert_motor3 = bool(config.get("invertMotor3", False))
    invert_motor4 = bool(config.get("invertMotor4", False))
    print(f"Config: invertMotor1={invert_motor1} invertMotor2={invert_motor2} "
          f"invertMotor3={invert_motor3} invertMotor4={invert_motor4}")

    port = args.port or autodetect_port()
    if not port:
        print("No --port specified and no Arduino-like serial port found. Use --list-ports to see options.")
        return

    try:
        ser = serial.Serial(port, args.baud, timeout=1)
    except serial.SerialException as e:
        print(f"Could not open serial port {port}: {e}")
        return

    # Give the Arduino time to reset after the serial connection opens
    time.sleep(2)
    print(f"Connected to {port} @ {args.baud} baud.")
    print("Sending motor commands. Press Ctrl+C to stop.\n")

    interval = 1.0 / args.rate if args.rate > 0 else 0.05
    last_sent = {}

    try:
        while True:
            pygame.event.pump()

            motor1_val = js.get_axis(AXIS_MOTOR1) if js.get_numaxes() > AXIS_MOTOR1 else 0.0
            motor2_val = js.get_axis(AXIS_MOTOR2) if js.get_numaxes() > AXIS_MOTOR2 else 0.0
            motor3_val = js.get_hat(HAT_MOTOR3)[HAT_MOTOR3_COMPONENT] if js.get_numhats() > HAT_MOTOR3 else 0.0

            motor4_forward = js.get_button(BUTTON_MOTOR4_FORWARD) if js.get_numbuttons() > BUTTON_MOTOR4_FORWARD else 0
            motor4_backward = js.get_button(BUTTON_MOTOR4_BACKWARD) if js.get_numbuttons() > BUTTON_MOTOR4_BACKWARD else 0
            if motor4_forward and not motor4_backward:
                motor4_val = 1.0
            elif motor4_backward and not motor4_forward:
                motor4_val = -1.0
            else:
                motor4_val = 0.0

            if invert_motor1:
                motor1_val = -motor1_val
            if invert_motor2:
                motor2_val = -motor2_val
            if invert_motor3:
                motor3_val = -motor3_val
            if invert_motor4:
                motor4_val = -motor4_val

            motor1_angle = axis_to_angle(motor1_val)
            motor2_angle = axis_to_angle(motor2_val)
            motor3_angle = axis_to_angle(motor3_val)
            motor4_angle = axis_to_angle(motor4_val, lo=MOTOR4_ANGLE_MIN, hi=MOTOR4_ANGLE_MAX)

            commands = {
                SERVO_MOTOR1: motor1_angle,
                SERVO_MOTOR2: motor2_angle,
                SERVO_MOTOR3: motor3_angle,
                SERVO_MOTOR4: motor4_angle,
            }

            # Only send a line if something changed, to keep serial traffic light
            if commands != last_sent:
                line = ",".join(f"{ch}:{ang}" for ch, ang in commands.items())
                ser.write((line + "\n").encode("ascii"))
                last_sent = commands

            print(f"motor1:{motor1_angle:3d} motor2:{motor2_angle:3d} "
                  f"motor3:{motor3_angle:3d} motor4:{motor4_angle:3d}", end="\r", flush=True)

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
