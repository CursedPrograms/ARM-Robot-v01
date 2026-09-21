# kinematics.jl - Inverse/forward kinematics for motors 1-4 (base, shoulder,
# elbow, wrist pitch). Julia counterpart of IK_controller.py's math - see
# that file for the coordinate frame and per-motor physical roles.

raw_to_deg(motors, n, raw_angle) = (raw_angle - motors[n]["rest"]) * motors[n]["kinematicSign"]

function deg_to_raw(motors, n, joint_deg)
    m = motors[n]
    raw = m["rest"] + joint_deg * m["kinematicSign"]
    clamped = clamp(raw, m["min"], m["max"])
    return round(Int, clamped), (m["min"] <= raw <= m["max"])
end

function forward_kinematics(motors, geometry, base_raw, shoulder_raw, elbow_raw, wrist_raw)
    base = deg2rad(raw_to_deg(motors, 1, base_raw))
    shoulder = deg2rad(raw_to_deg(motors, 2, shoulder_raw))
    elbow = deg2rad(raw_to_deg(motors, 3, elbow_raw))
    wrist = deg2rad(raw_to_deg(motors, 4, wrist_raw))

    l1 = geometry["upperArmLength"]
    l2 = geometry["forearmLength"]
    l3 = geometry["wristLength"]

    r = l1 * cos(shoulder) + l2 * cos(shoulder + elbow) + l3 * cos(shoulder + elbow + wrist)
    z = geometry["baseHeight"] +
        l1 * sin(shoulder) + l2 * sin(shoulder + elbow) + l3 * sin(shoulder + elbow + wrist)

    x = r * cos(base)
    y = r * sin(base)
    return x, y, z
end

"""
    inverse_kinematics(motors, geometry, x, y, z; pitch_deg=0.0, elbow_down=false)

Target (x, y, z) mm + desired end-effector pitch (deg, 0 = level) -> raw
servo angles for motors 1-4 as a Dict, or `nothing` if unreachable.
"""
function inverse_kinematics(motors, geometry, x, y, z; pitch_deg::Real=0.0, elbow_down::Bool=false)
    l1 = geometry["upperArmLength"]
    l2 = geometry["forearmLength"]
    l3 = geometry["wristLength"]

    base_deg = rad2deg(atan(y, x))
    r = hypot(x, y)
    z_rel = z - geometry["baseHeight"]

    pitch = deg2rad(pitch_deg)
    r_w = r - l3 * cos(pitch)
    z_w = z_rel - l3 * sin(pitch)

    dist2 = r_w * r_w + z_w * z_w
    cos_elbow = (dist2 - l1 * l1 - l2 * l2) / (2 * l1 * l2)
    (-1.0 <= cos_elbow <= 1.0) || return nothing

    elbow_mag = acos(cos_elbow)
    elbow = elbow_down ? -elbow_mag : elbow_mag

    shoulder = atan(z_w, r_w) - atan(l2 * sin(elbow), l1 + l2 * cos(elbow))
    wrist = pitch - shoulder - elbow

    base_raw, base_ok = deg_to_raw(motors, 1, base_deg)
    shoulder_raw, shoulder_ok = deg_to_raw(motors, 2, rad2deg(shoulder))
    elbow_raw, elbow_ok = deg_to_raw(motors, 3, rad2deg(elbow))
    wrist_raw, wrist_ok = deg_to_raw(motors, 4, rad2deg(wrist))

    (base_ok && shoulder_ok && elbow_ok && wrist_ok) || return nothing

    return Dict(1 => base_raw, 2 => shoulder_raw, 3 => elbow_raw, 4 => wrist_raw)
end
