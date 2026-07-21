#!/usr/bin/env python3
"""
joystick_test.py - Standalone joystick/controller input tester.

Lists connected joysticks and live-prints axis, button, and hat values
so you can verify wiring/mapping before running scripts/run.py.

Requires:
    pip install pygame

Usage:
    python joystick_test.py            # test device 0
    python joystick_test.py --list     # list connected joysticks and exit
    python joystick_test.py --device 1 # test a specific joystick index
"""

import argparse
import datetime
import sys
import time
from pathlib import Path

try:
    import pygame
except ImportError:
    print("pygame is not installed. Install it with: pip install pygame")
    sys.exit(1)


LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "joystick_test"


def open_log_file():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"{timestamp}.log"
    return open(log_path, "w", encoding="utf-8")


def list_joysticks():
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


def test_joystick(device):
    pygame.joystick.init()
    count = pygame.joystick.get_count()
    if count == 0:
        print("No joystick/controller devices found. Plug one in and try again.")
        return
    if device >= count:
        print(f"Device index {device} out of range (only {count} found). Run --list to see options.")
        return

    js = pygame.joystick.Joystick(device)
    js.init()
    print(f"Using joystick: {js.get_name()}")
    print(f"Axes: {js.get_numaxes()}  Buttons: {js.get_numbuttons()}  Hats: {js.get_numhats()}")
    print("Move sticks / press buttons to see live values. Ctrl+C to stop.\n")

    log_file = open_log_file()
    print(f"Logging to {log_file.name}")
    log_file.write(f"Joystick: {js.get_name()}\n")
    log_file.write(f"Axes: {js.get_numaxes()}  Buttons: {js.get_numbuttons()}  Hats: {js.get_numhats()}\n")

    try:
        while True:
            pygame.event.pump()

            axes = " ".join(f"A{i}:{js.get_axis(i):+.2f}" for i in range(js.get_numaxes()))
            buttons = " ".join(f"B{i}:{js.get_button(i)}" for i in range(js.get_numbuttons()))
            hats = " ".join(f"H{i}:{js.get_hat(i)}" for i in range(js.get_numhats()))
            line = f"{axes}  {buttons}  {hats}"

            print(line, end="\r", flush=True)
            timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            log_file.write(f"{timestamp} {line}\n")
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        log_file.close()
        js.quit()


def main():
    parser = argparse.ArgumentParser(description="Standalone joystick/controller input tester.")
    parser.add_argument("--device", type=int, default=0, help="Joystick index to test (default 0)")
    parser.add_argument("--list", action="store_true", help="List joystick devices and exit")
    args = parser.parse_args()

    pygame.init()

    if args.list:
        list_joysticks()
    else:
        test_joystick(args.device)

    pygame.joystick.quit()
    pygame.quit()


if __name__ == "__main__":
    main()
