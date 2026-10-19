// keys_window.h - every key and joystick input in its own window (F1), the
// C++ counterpart of scripts/keymap.py's window. It shows scripts/keymap.json,
// which keymap.py writes (python scripts/keymap.py --json scripts/keymap.json).
#pragma once

#include <windows.h>

// Opens the window, or brings it to the front if it's already open.
void openKeysWindow(HWND owner);
