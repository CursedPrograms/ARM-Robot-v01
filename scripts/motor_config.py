#!/usr/bin/env python3
"""
motor_config.py - Shared motor configuration, loaded from scripts/config.json.

Every motor-driving script (controller.py, slider_controller.py, and any
future one) should call load_motor_config() instead of hardcoding its own
servo channel numbers, angle ranges, resting angles, or invert flags - so
config.json stays the single source of truth for the arm's physical limits.
"""

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

# Fallback per-motor settings, used for any motor missing from config.json
# (or if the file itself is missing/unreadable).
DEFAULT_MOTORS = {
    1: {"channel": 0, "min": 0, "max": 270, "rest": 135, "invert": False, "kinematicSign": 1},
    2: {"channel": 1, "min": 0, "max": 270, "rest": 135, "invert": False, "kinematicSign": 1},
    3: {"channel": 2, "min": 0, "max": 270, "rest": 135, "invert": False, "kinematicSign": 1},
    4: {"channel": 3, "min": 0, "max": 270, "rest": 135, "invert": False, "kinematicSign": 1},
    5: {"channel": 4, "min": 0, "max": 270, "rest": 135, "invert": False, "kinematicSign": 1},
    6: {"channel": 5, "min": 0, "max": 270, "rest": 135, "invert": False, "kinematicSign": 1},
}

# Fallback arm geometry (mm), used if config.json has no "geometry" section
# or is missing/unreadable. All zero until measured - see config.json.
DEFAULT_GEOMETRY = {
    "units": "mm",
    "baseHeight": 0,
    "upperArmLength": 0,
    "forearmLength": 0,
    "wristLength": 0,
}


def load_motor_config():
    """Return {motor_number: {"channel", "min", "max", "rest", "invert"}},
    merging config.json's "motors" section over DEFAULT_MOTORS."""
    motors = {n: dict(settings) for n, settings in DEFAULT_MOTORS.items()}

    if not CONFIG_PATH.exists():
        return motors

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"Warning: could not read {CONFIG_PATH.name} ({e}), using default motor config.")
        return motors

    for key, overrides in data.get("motors", {}).items():
        try:
            n = int(key)
        except ValueError:
            continue
        motors.setdefault(n, dict(DEFAULT_MOTORS.get(n, DEFAULT_MOTORS[1])))
        motors[n].update(overrides)

    return motors


def load_geometry():
    """Return the arm's link-length geometry (mm), merging config.json's
    "geometry" section over DEFAULT_GEOMETRY. All-zero lengths mean the arm
    hasn't been measured yet - IK_controller.py checks for this."""
    geometry = dict(DEFAULT_GEOMETRY)

    if not CONFIG_PATH.exists():
        return geometry

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"Warning: could not read {CONFIG_PATH.name} ({e}), using default geometry.")
        return geometry

    geometry.update(data.get("geometry", {}))
    return geometry
