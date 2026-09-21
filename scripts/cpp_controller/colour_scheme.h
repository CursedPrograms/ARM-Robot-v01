// colour_scheme.h - UI colours from colour_scheme.xml at the repo root, shared
// by every controller. Edit that file and restart - no rebuild. Any role
// missing from it (or the whole file being unreadable) falls back to a
// built-in default.
#pragma once

#include <windows.h>

#include <string>

// The colour for a role such as "background" or "warn".
COLORREF schemeColour(const std::string& role);
