// kinematics.h - Inverse/forward kinematics for the arm, driving motors 1-4
// (base, shoulder, elbow, wrist pitch). Direct port of IK_controller.py's
// math - see that file for the coordinate frame and unit conventions.
#pragma once

#include <map>
#include <optional>

#include "motor_config.h"

// Raw servo angles (motors 1-4) -> (x, y, z) tip position in mm.
void forwardKinematics(const MotorMap& motors, const Geometry& geometry,
                        double baseRaw, double shoulderRaw, double elbowRaw, double wristRaw,
                        double& x, double& y, double& z);

// Target (x, y, z) mm + desired end-effector pitch (deg, 0 = level) -> raw
// servo angles for motors 1-4, or std::nullopt if unreachable (either
// geometrically, or within this arm's configured servo ranges).
std::optional<std::map<int, int>> inverseKinematics(
    const MotorMap& motors, const Geometry& geometry,
    double x, double y, double z,
    double pitchDeg = 0.0, bool elbowDown = false);
