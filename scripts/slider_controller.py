#!/usr/bin/env python3
"""
slider_controller.py - Manual on-screen slider GUI to drive motor 1-6 over
USB serial, talking to the Arduino running scripts/arm/arm.ino. No joystick
required.

Per-motor servo channel, angle range, and resting angle come from
config.json (see motor_config.py) - edit that file to tune the arm's
physical limits without touching this script.

Drag each slider with the mouse to set that motor's angle. The current angle
is shown as text next to each slider and sent to the Arduino over serial
whenever it changes. "Reset Position" snaps every slider back to its
resting angle from config.json.

Requires:
    pip install pygame pyserial

Usage:
    python slider_controller.py --list-ports   # find your Arduino's port
    python slider_controller.py --port COM6
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

from motor_config import load_motor_config
from colour_scheme import rgb

# Descriptions that identify likely Arduino USB-serial adapters, for --port auto-detect
ARDUINO_HINTS = ("arduino", "ch340", "usb-serial", "usb serial", "cp210", "ftdi")

WINDOW_WIDTH, WINDOW_HEIGHT = 480, 500
MARGIN_TOP = 80
ROW_HEIGHT = 70
SLIDER_X = 150
SLIDER_WIDTH = 260
KNOB_RADIUS = 10

# Colours come from colour_scheme.xml at the repo root.
BG_COLOR = rgb("background")
TRACK_COLOR = rgb("track")
KNOB_COLOR = rgb("accent")
TEXT_COLOR = rgb("text")
STATUS_COLOR = rgb("text_dim")
BUTTON_COLOR = rgb("button")
BUTTON_HOVER_COLOR = rgb("button_hover")

RESET_BUTTON_RECT = pygame.Rect((WINDOW_WIDTH - 160) // 2, WINDOW_HEIGHT - 50, 160, 36)


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


def main():
    parser = argparse.ArgumentParser(description="Slider GUI -> Arduino motor controller over USB serial (no joystick).")
    parser.add_argument("--port", type=str, default=None, help="Serial port, e.g. COM6 (auto-detected if omitted)")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baud rate (default 115200, must match .ino)")
    parser.add_argument("--list-ports", action="store_true", help="List serial ports and exit")
    args = parser.parse_args()

    if args.list_ports:
        list_serial_ports()
        return

    port = args.port or autodetect_port()
    ser = None
    status = "No serial port - running in display-only mode."
    if not port:
        print("No --port specified and no Arduino-like serial port found. Use --list-ports to see options.")
        print("Continuing without serial output.")
    else:
        try:
            ser = serial.Serial(port, args.baud, timeout=1)
            time.sleep(2)  # give the Arduino time to reset after the serial connection opens
            status = f"Connected to {port} @ {args.baud} baud."
            print(status)
        except serial.SerialException as e:
            status = f"Could not open {port}: {e}"
            print(status + " Continuing without serial output.")

    pygame.init()
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("Motor Sliders")
    font = pygame.font.SysFont(None, 26)
    small_font = pygame.font.SysFont(None, 20)
    clock = pygame.time.Clock()

    motors = load_motor_config()
    sliders = [
        Slider(f"Motor {n}", motors[n]["channel"], motors[n]["min"], motors[n]["max"],
               motors[n]["rest"], MARGIN_TOP + i * ROW_HEIGHT)
        for i, n in enumerate(sorted(motors))
    ]

    last_sent = {}
    running = True
    try:
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and RESET_BUTTON_RECT.collidepoint(event.pos):
                    for slider in sliders:
                        slider.angle = slider.rest
                else:
                    for slider in sliders:
                        slider.handle_event(event)

            commands = {s.channel: s.angle for s in sliders}
            if commands != last_sent:
                line = ",".join(f"{ch}:{ang}" for ch, ang in commands.items())
                if ser is not None:
                    ser.write((line + "\n").encode("ascii"))
                last_sent = commands

            screen.fill(BG_COLOR)
            title_surf = font.render("Drag sliders to set each motor angle", True, TEXT_COLOR)
            screen.blit(title_surf, (20, 20))
            status_surf = small_font.render(status, True, STATUS_COLOR)
            screen.blit(status_surf, (20, 46))

            for slider in sliders:
                slider.draw(screen, font)

            button_hover = RESET_BUTTON_RECT.collidepoint(pygame.mouse.get_pos())
            pygame.draw.rect(screen, BUTTON_HOVER_COLOR if button_hover else BUTTON_COLOR, RESET_BUTTON_RECT, border_radius=6)
            reset_label = font.render("Reset Position", True, TEXT_COLOR)
            screen.blit(reset_label, reset_label.get_rect(center=RESET_BUTTON_RECT.center))

            pygame.display.flip()
            clock.tick(60)
    finally:
        if ser is not None:
            ser.close()
        pygame.quit()


if __name__ == "__main__":
    main()
