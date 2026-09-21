#!/usr/bin/env python3
"""
colour_scheme.py - Shared UI colours, loaded from colour_scheme.xml at the
repo root. Every Python UI (controller.py, slider_controller.py) asks for its
colours by role name (rgb("background"), rgb("button_hover"), ...) instead of
hardcoding them, so editing that one file restyles them all.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

SCHEME_PATH = Path(__file__).resolve().parent.parent / "colour_scheme.xml"

# Fallback for any role missing from colour_scheme.xml (or if the file is
# missing/unreadable). Keep in sync with the XML.
DEFAULTS = {
    "background": "#33292F",
    "panel": "#331F2B",
    "border": "#361529",
    "text": "#FFFFFF",
    "text_dim": "#C9B6C1",
    "button": "#361529",
    "button_hover": "#691548",
    "button_active": "#9C0060",
    "button_disabled": "#331F2B",
    "accent": "#9C0060",
    "accent_hover": "#C21F82",
    "track": "#691548",
    "selected": "#691548",
    "danger": "#963232",
    "danger_hover": "#AD3A3A",
    "warn": "#F08C3C",
}


def _parse_hex(value):
    value = value.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError(f"expected #RRGGBB, got {value!r}")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def load_scheme():
    """Return {role: (r, g, b)}, merging colour_scheme.xml over DEFAULTS."""
    scheme = {name: _parse_hex(value) for name, value in DEFAULTS.items()}

    if not SCHEME_PATH.exists():
        return scheme

    try:
        root = ET.parse(SCHEME_PATH).getroot()
    except (OSError, ET.ParseError) as e:
        print(f"Warning: could not read {SCHEME_PATH.name} ({e}), using default colours.")
        return scheme

    for el in root.iter("colour"):
        name = el.get("name")
        try:
            scheme[name] = _parse_hex(el.get("value", ""))
        except ValueError as e:
            print(f"Warning: {SCHEME_PATH.name}: bad value for '{name}' ({e}), keeping default.")
    return scheme


_scheme = load_scheme()


def rgb(name):
    """(r, g, b) for a role, e.g. rgb("background")."""
    return _scheme[name]
