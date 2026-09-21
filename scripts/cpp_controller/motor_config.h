// motor_config.h - Shared motor configuration, loaded from config.json at the
// repo root. Mirrors scripts/motor_config.py so the C++ and Python
// controllers agree on channel numbers, angle ranges, resting angles,
// invert flags, and arm geometry.
#pragma once

#include <map>
#include <string>

struct Motor {
    int channel = 0;
    int min = 0;
    int max = 270;
    int rest = 135;
    bool invert = false;
    int kinematicSign = 1;
};

struct Geometry {
    double baseHeight = 0;
    double upperArmLength = 0;
    double forearmLength = 0;
    double wristLength = 0;
};

using MotorMap = std::map<int, Motor>;

// Directory containing this executable's config.json (repo root, one level
// above scripts/), resolved relative to the running .exe's own path.
std::string configPath();

// The repo root directory (containing config.json), i.e. configPath() minus
// the filename. Used to locate scripts/macros/ and scripts/web/ regardless
// of where the .exe was built to.
std::string repoRoot();

MotorMap loadMotorConfig();
Geometry loadGeometry();
bool geometryReady(const Geometry& g);
