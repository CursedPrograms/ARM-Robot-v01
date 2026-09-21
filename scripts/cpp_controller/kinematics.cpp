#include "kinematics.h"

#include <algorithm>
#include <cmath>

namespace {

constexpr double PI = 3.14159265358979323846;
double toRad(double deg) { return deg * PI / 180.0; }
double toDeg(double rad) { return rad * 180.0 / PI; }

// Convert a motor's raw servo angle to a kinematic joint angle (degrees),
// relative to its configured resting position.
double rawToDeg(const MotorMap& motors, int n, double rawAngle) {
    const Motor& m = motors.at(n);
    return (rawAngle - m.rest) * m.kinematicSign;
}

// Convert a kinematic joint angle (degrees) to a motor's raw servo angle,
// clamped to its configured range. Returns whether it fit before clamping.
int degToRaw(const MotorMap& motors, int n, double jointDeg, bool& inRange) {
    const Motor& m = motors.at(n);
    double raw = m.rest + jointDeg * m.kinematicSign;
    double clamped = std::max<double>(m.min, std::min<double>(m.max, raw));
    inRange = (raw >= m.min && raw <= m.max);
    return static_cast<int>(std::lround(clamped));
}

} // namespace

void forwardKinematics(const MotorMap& motors, const Geometry& geometry,
                        double baseRaw, double shoulderRaw, double elbowRaw, double wristRaw,
                        double& x, double& y, double& z) {
    double base = toRad(rawToDeg(motors, 1, baseRaw));
    double shoulder = toRad(rawToDeg(motors, 2, shoulderRaw));
    double elbow = toRad(rawToDeg(motors, 3, elbowRaw));
    double wrist = toRad(rawToDeg(motors, 4, wristRaw));

    double l1 = geometry.upperArmLength;
    double l2 = geometry.forearmLength;
    double l3 = geometry.wristLength;

    // Position in the vertical plane before applying base yaw.
    double r = l1 * std::cos(shoulder) + l2 * std::cos(shoulder + elbow) + l3 * std::cos(shoulder + elbow + wrist);
    z = geometry.baseHeight +
        l1 * std::sin(shoulder) + l2 * std::sin(shoulder + elbow) + l3 * std::sin(shoulder + elbow + wrist);

    x = r * std::cos(base);
    y = r * std::sin(base);
}

std::optional<std::map<int, int>> inverseKinematics(
    const MotorMap& motors, const Geometry& geometry,
    double x, double y, double z,
    double pitchDeg, bool elbowDown) {
    double l1 = geometry.upperArmLength;
    double l2 = geometry.forearmLength;
    double l3 = geometry.wristLength;

    double baseDeg = toDeg(std::atan2(y, x));
    double r = std::hypot(x, y);
    double zRel = z - geometry.baseHeight;

    double pitch = toRad(pitchDeg);
    // Wrist-joint position: back off from the target tip by the wrist link,
    // along the desired approach direction.
    double rw = r - l3 * std::cos(pitch);
    double zw = zRel - l3 * std::sin(pitch);

    double dist2 = rw * rw + zw * zw;
    double cosElbow = (dist2 - l1 * l1 - l2 * l2) / (2 * l1 * l2);
    if (cosElbow < -1.0 || cosElbow > 1.0) return std::nullopt; // target out of reach

    double elbowMag = std::acos(cosElbow);
    double elbow = elbowDown ? -elbowMag : elbowMag;

    double shoulder = std::atan2(zw, rw) - std::atan2(l2 * std::sin(elbow), l1 + l2 * std::cos(elbow));
    double wrist = pitch - shoulder - elbow;

    bool baseOk, shoulderOk, elbowOk, wristOk;
    int baseRaw = degToRaw(motors, 1, baseDeg, baseOk);
    int shoulderRaw = degToRaw(motors, 2, toDeg(shoulder), shoulderOk);
    int elbowRaw = degToRaw(motors, 3, toDeg(elbow), elbowOk);
    int wristRaw = degToRaw(motors, 4, toDeg(wrist), wristOk);

    if (!(baseOk && shoulderOk && elbowOk && wristOk)) return std::nullopt;

    return std::map<int, int>{{1, baseRaw}, {2, shoulderRaw}, {3, elbowRaw}, {4, wristRaw}};
}
