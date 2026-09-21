// Kinematics.cs - Inverse kinematics for motors 1-4 (base, shoulder, elbow,
// wrist pitch). C# counterpart of IK_controller.py's inverse_kinematics() -
// see that file for the coordinate frame and per-motor physical roles.

namespace ArmController;

public static class Kinematics
{
    static (int Raw, bool InRange) DegToRaw(Motor m, double jointDeg)
    {
        double raw = m.Rest + jointDeg * m.KinematicSign;
        double clamped = Math.Clamp(raw, m.Min, m.Max);
        return ((int)Math.Round(clamped), raw >= m.Min && raw <= m.Max);
    }

    /// <summary>
    /// Target (x, y, z) mm + end-effector pitch (deg, 0 = level) -> raw servo
    /// angles for motors 1-4, or null if unreachable.
    /// </summary>
    public static Dictionary<int, int>? InverseKinematics(
        IReadOnlyDictionary<int, Motor> motors, ArmGeometry g,
        double x, double y, double z, double pitchDeg = 0, bool elbowDown = false)
    {
        double l1 = g.UpperArmLength, l2 = g.ForearmLength, l3 = g.WristLength;

        double baseDeg = Math.Atan2(y, x) * 180.0 / Math.PI;
        double r = Math.Sqrt(x * x + y * y);
        double zRel = z - g.BaseHeight;

        double pitch = pitchDeg * Math.PI / 180.0;
        double rW = r - l3 * Math.Cos(pitch);
        double zW = zRel - l3 * Math.Sin(pitch);

        double dist2 = rW * rW + zW * zW;
        double cosElbow = (dist2 - l1 * l1 - l2 * l2) / (2 * l1 * l2);
        if (cosElbow < -1.0 || cosElbow > 1.0) return null;

        double elbowMag = Math.Acos(cosElbow);
        double elbow = elbowDown ? -elbowMag : elbowMag;

        double shoulder = Math.Atan2(zW, rW) - Math.Atan2(l2 * Math.Sin(elbow), l1 + l2 * Math.Cos(elbow));
        double wrist = pitch - shoulder - elbow;

        double ToDeg(double rad) => rad * 180.0 / Math.PI;
        var (baseRaw, baseOk) = DegToRaw(motors[1], baseDeg);
        var (shoulderRaw, shoulderOk) = DegToRaw(motors[2], ToDeg(shoulder));
        var (elbowRaw, elbowOk) = DegToRaw(motors[3], ToDeg(elbow));
        var (wristRaw, wristOk) = DegToRaw(motors[4], ToDeg(wrist));

        if (!(baseOk && shoulderOk && elbowOk && wristOk)) return null;

        return new Dictionary<int, int> { [1] = baseRaw, [2] = shoulderRaw, [3] = elbowRaw, [4] = wristRaw };
    }
}
