// macros.h - Record/replay motion macros, saved to scripts/macros/ as JSON
// in the exact same shape controller.py writes, so macros recorded by either
// controller are interchangeable.
#pragma once

#include <map>
#include <string>
#include <vector>

struct MacroStep {
    double t = 0.0;                  // seconds since recording started
    std::map<int, int> commands;     // channel -> angle
};

struct MacroFile {
    std::string path;   // full path
    std::string name;   // filename without extension, for display
};

std::string macrosDir();

// Newest-first (filename sorts by embedded timestamp), matching
// controller.py's list_macros().
std::vector<MacroFile> listMacros();

// Writes a new macro_<timestamp>.json file and returns its full path.
std::string saveMacro(const std::vector<MacroStep>& steps);

std::vector<MacroStep> loadMacro(const std::string& path);
