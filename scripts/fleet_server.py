#!/usr/bin/env python3
"""
fleet_server.py - HTTP bridge that lets RIFT (Real-time Intelligent Fleet
Technology, https://github.com/CursedPrograms/RIFT) see and control this arm
over the network, the same way it talks to MILA/WHIP/NORA/KIDA.

The Arduino only speaks USB serial, so this script is the always-on bridge:
it owns the serial connection, exposes a small HTTP API for setting motor
angles, and heartbeats a /register call to RIFT's (or NORA's) fleet
registry so this arm shows up in the dashboard, same wire protocol as
RIFT's Fleet/register.py.

Per-motor servo channel, angle range, resting angle, and invert flag come
from config.json (see motor_config.py), same as controller.py and
slider_controller.py.

Requires:
    pip install flask requests pyserial

Usage:
    python fleet_server.py --list-ports              # find the Arduino's port
    python fleet_server.py --serial-port COM6
    python fleet_server.py --serial-port COM6 --port 5011 --rift-host 192.168.4.1 --rift-port 5000

HTTP API (defaults to http://<this machine>:5011):
    GET /status                        -> connection state + every motor's current angle
    GET /cmd?motor=<1-6>&angle=<deg>   -> set one motor's angle (clamped to its configured range)
    GET /reset                         -> reset every motor to its resting angle
    GET /reset?motor=<1-6>             -> reset a single motor to its resting angle
"""

import argparse
import sys
import threading
import time

try:
    from flask import Flask, jsonify, request
except ImportError:
    print("flask is not installed. Install it with: pip install flask")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("requests is not installed. Install it with: pip install requests")
    sys.exit(1)

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("pyserial is not installed. Install it with: pip install pyserial")
    sys.exit(1)

from motor_config import load_motor_config

FLEET_NAME = "ARM"
FLEET_TYPE = "robot"
FLEET_CAPABILITIES = ["servo_control", "6dof", "arm"]

# Descriptions that identify likely Arduino USB-serial adapters, for --serial-port auto-detect
ARDUINO_HINTS = ("arduino", "ch340", "usb-serial", "usb serial", "cp210", "ftdi")

# Must stay under RIFT's FLEET_TTL_SECS (20s) - same cadence as RIFT's own Fleet/register.py.
HEARTBEAT_SECS = 10


def list_serial_ports():
    ports = list_ports.comports()
    if not ports:
        print("No serial ports found.")
        return
    print("Available serial ports:")
    for p in ports:
        print(f"  {p.device}  -  {p.description}")


def autodetect_serial_port():
    for p in list_ports.comports():
        if any(hint in p.description.lower() for hint in ARDUINO_HINTS):
            return p.device
    return None


class ArmLink:
    """Owns the serial connection to the Arduino and tracks each motor's last-sent angle."""

    def __init__(self, serial_port, baud, motors):
        self.motors = motors
        self.angles = {n: m["rest"] for n, m in motors.items()}
        self.lock = threading.Lock()
        self.port = serial_port
        self.ser = None
        if serial_port:
            try:
                self.ser = serial.Serial(serial_port, baud, timeout=1)
                time.sleep(2)  # give the Arduino time to reset after the serial connection opens
                print(f"Connected to {serial_port} @ {baud} baud.")
            except serial.SerialException as e:
                print(f"Could not open {serial_port}: {e}. Running in status-only mode.")

    @property
    def connected(self):
        return self.ser is not None

    def set_motor(self, n, angle):
        m = self.motors[n]
        angle = max(m["min"], min(m["max"], int(angle)))
        with self.lock:
            self.angles[n] = angle
            if self.ser is not None:
                self.ser.write(f"{m['channel']}:{angle}\n".encode("ascii"))
        return angle

    def reset_motor(self, n):
        return self.set_motor(n, self.motors[n]["rest"])

    def reset_all(self):
        with self.lock:
            line = ",".join(f"{self.motors[n]['channel']}:{self.motors[n]['rest']}" for n in self.motors)
            for n in self.motors:
                self.angles[n] = self.motors[n]["rest"]
            if self.ser is not None:
                self.ser.write((line + "\n").encode("ascii"))
        return dict(self.angles)

    def status(self):
        with self.lock:
            return {
                "connected": self.connected,
                "port": self.port,
                "motors": {
                    str(n): {"channel": m["channel"], "angle": self.angles[n], "min": m["min"], "max": m["max"]}
                    for n, m in self.motors.items()
                },
            }


def start_fleet_heartbeat(rift_host, rift_port, interval=HEARTBEAT_SECS):
    """Background thread that repeatedly POSTs /register to RIFT/NORA. Safe to
    call even if the target isn't reachable yet - it just keeps retrying."""
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


def create_app(link):
    app = Flask(__name__)

    @app.route("/ping")
    def ping():
        return f"{FLEET_NAME} alive", 200, {"Content-Type": "text/plain"}

    @app.route("/status")
    def status():
        return jsonify(link.status())

    @app.route("/cmd")
    def cmd():
        try:
            motor = int(request.args["motor"])
            angle = int(request.args["angle"])
        except (KeyError, ValueError):
            return jsonify({"error": "expected ?motor=<1-6>&angle=<degrees>"}), 400
        if motor not in link.motors:
            return jsonify({"error": f"unknown motor {motor}"}), 400
        angle = link.set_motor(motor, angle)
        return jsonify({"motor": motor, "angle": angle})

    @app.route("/reset")
    def reset():
        motor = request.args.get("motor", type=int)
        if motor is not None:
            if motor not in link.motors:
                return jsonify({"error": f"unknown motor {motor}"}), 400
            angle = link.reset_motor(motor)
            return jsonify({"motor": motor, "angle": angle})
        return jsonify(link.reset_all())

    return app


def main():
    parser = argparse.ArgumentParser(
        description="HTTP bridge that registers this arm with RIFT and forwards motor commands over USB serial."
    )
    parser.add_argument("--serial-port", type=str, default=None, help="Arduino serial port, e.g. COM6 (auto-detected if omitted)")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baud rate (default 115200, must match .ino)")
    parser.add_argument("--port", type=int, default=5011, help="Port this HTTP server listens on (default 5011)")
    parser.add_argument("--rift-host", type=str, default="127.0.0.1", help="RIFT/NORA fleet-registry host (default 127.0.0.1)")
    parser.add_argument("--rift-port", type=int, default=5000, help="RIFT/NORA fleet-registry port (default 5000)")
    parser.add_argument("--no-register", action="store_true", help="Don't heartbeat to the fleet registry, just serve the HTTP API")
    parser.add_argument("--list-ports", action="store_true", help="List serial ports and exit")
    args = parser.parse_args()

    if args.list_ports:
        list_serial_ports()
        return

    motors = load_motor_config()
    serial_port = args.serial_port or autodetect_serial_port()
    if not serial_port:
        print("No --serial-port specified and no Arduino-like serial port found. Use --list-ports to see options.")
        print("Starting anyway in status-only mode (no serial output).")

    link = ArmLink(serial_port, args.baud, motors)
    app = create_app(link)

    if not args.no_register:
        print(f"Heartbeating to RIFT/NORA at {args.rift_host}:{args.rift_port} every {HEARTBEAT_SECS}s as '{FLEET_NAME}'.")
        start_fleet_heartbeat(args.rift_host, args.rift_port)

    print(f"Serving on http://0.0.0.0:{args.port}  (status: /status, control: /cmd?motor=&angle=, reset: /reset)")
    app.run(host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
