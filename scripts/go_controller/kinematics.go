package main

// Inverse kinematics for motors 1-4 (base, shoulder, elbow, wrist pitch). Go
// counterpart of IK_controller.py's inverse_kinematics() - see that file for
// the coordinate frame and per-motor physical roles.

import "math"

func degToRaw(m Motor, jointDeg float64) (int, bool) {
	raw := float64(m.Rest) + jointDeg*m.KinematicSign
	clamped := math.Min(math.Max(raw, float64(m.Min)), float64(m.Max))
	// Python's round() is round-half-to-even; match it so all controllers agree.
	return int(math.RoundToEven(clamped)), raw >= float64(m.Min) && raw <= float64(m.Max)
}

func deg(rad float64) float64 { return rad * 180 / math.Pi }

// inverseKinematics maps a target (x, y, z) mm + end-effector pitch (deg, 0 =
// level) to raw servo angles for motors 1-4; ok is false if it's unreachable.
func inverseKinematics(motors map[int]Motor, g Geometry, x, y, z, pitchDeg float64, elbowDown bool) (map[int]int, bool) {
	l1, l2, l3 := g.UpperArm, g.Forearm, g.Wrist

	baseDeg := deg(math.Atan2(y, x))
	r := math.Hypot(x, y)
	zRel := z - g.BaseHeight

	pitch := pitchDeg * math.Pi / 180
	rW := r - l3*math.Cos(pitch)
	zW := zRel - l3*math.Sin(pitch)

	dist2 := rW*rW + zW*zW
	cosElbow := (dist2 - l1*l1 - l2*l2) / (2 * l1 * l2)
	if cosElbow < -1 || cosElbow > 1 {
		return nil, false // out of reach
	}

	elbow := math.Acos(cosElbow)
	if elbowDown {
		elbow = -elbow
	}
	shoulder := math.Atan2(zW, rW) - math.Atan2(l2*math.Sin(elbow), l1+l2*math.Cos(elbow))
	wrist := pitch - shoulder - elbow

	baseRaw, baseOK := degToRaw(motors[1], baseDeg)
	shoulderRaw, shoulderOK := degToRaw(motors[2], deg(shoulder))
	elbowRaw, elbowOK := degToRaw(motors[3], deg(elbow))
	wristRaw, wristOK := degToRaw(motors[4], deg(wrist))
	if !(baseOK && shoulderOK && elbowOK && wristOK) {
		return nil, false // solvable, but outside this arm's servo ranges
	}
	return map[int]int{1: baseRaw, 2: shoulderRaw, 3: elbowRaw, 4: wristRaw}, true
}
