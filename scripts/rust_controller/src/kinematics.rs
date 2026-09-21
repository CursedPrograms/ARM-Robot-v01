//! Inverse kinematics for motors 1-4 (base, shoulder, elbow, wrist pitch).
//! Rust counterpart of IK_controller.py's `inverse_kinematics()` - see that
//! file for the coordinate frame and per-motor physical roles.

use crate::config::{Geometry, Motor, Motors};
use std::collections::BTreeMap;

fn deg_to_raw(m: &Motor, joint_deg: f64) -> (i32, bool) {
    let raw = m.rest as f64 + joint_deg * m.kinematic_sign;
    let clamped = raw.clamp(m.min as f64, m.max as f64);
    // Python's round() is round-half-to-even; match it so all controllers agree.
    (round_half_even(clamped), raw >= m.min as f64 && raw <= m.max as f64)
}

fn round_half_even(x: f64) -> i32 {
    let r = x.round();
    if (x - x.trunc()).abs() == 0.5 && r % 2.0 != 0.0 {
        (r - x.signum()) as i32
    } else {
        r as i32
    }
}

/// Target (x, y, z) mm + end-effector pitch (deg, 0 = level) -> raw servo
/// angles for motors 1-4, or `None` if unreachable.
pub fn inverse_kinematics(
    motors: &Motors,
    g: &Geometry,
    x: f64,
    y: f64,
    z: f64,
    pitch_deg: f64,
    elbow_down: bool,
) -> Option<BTreeMap<i32, i32>> {
    let (l1, l2, l3) = (g.upper_arm, g.forearm, g.wrist);

    let base_deg = y.atan2(x).to_degrees();
    let r = x.hypot(y);
    let z_rel = z - g.base_height;

    let pitch = pitch_deg.to_radians();
    let r_w = r - l3 * pitch.cos();
    let z_w = z_rel - l3 * pitch.sin();

    let dist2 = r_w * r_w + z_w * z_w;
    let cos_elbow = (dist2 - l1 * l1 - l2 * l2) / (2.0 * l1 * l2);
    if !(-1.0..=1.0).contains(&cos_elbow) {
        return None; // out of reach
    }

    let elbow_mag = cos_elbow.acos();
    let elbow = if elbow_down { -elbow_mag } else { elbow_mag };
    let shoulder = z_w.atan2(r_w) - (l2 * elbow.sin()).atan2(l1 + l2 * elbow.cos());
    let wrist = pitch - shoulder - elbow;

    let (base_raw, base_ok) = deg_to_raw(&motors[&1], base_deg);
    let (shoulder_raw, shoulder_ok) = deg_to_raw(&motors[&2], shoulder.to_degrees());
    let (elbow_raw, elbow_ok) = deg_to_raw(&motors[&3], elbow.to_degrees());
    let (wrist_raw, wrist_ok) = deg_to_raw(&motors[&4], wrist.to_degrees());

    if !(base_ok && shoulder_ok && elbow_ok && wrist_ok) {
        return None; // solvable, but outside this arm's servo ranges
    }
    Some(BTreeMap::from([(1, base_raw), (2, shoulder_raw), (3, elbow_raw), (4, wrist_raw)]))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn motors() -> Motors {
        (1..=6)
            .map(|n| (n, Motor { channel: n - 1, min: 0, max: 270, rest: 135, invert: false, kinematic_sign: 1.0 }))
            .collect()
    }

    #[test]
    fn straight_out_is_reachable() {
        let g = Geometry { base_height: 0.0, upper_arm: 100.0, forearm: 100.0, wrist: 0.0 };
        let sol = inverse_kinematics(&motors(), &g, 150.0, 0.0, 0.0, 0.0, false).unwrap();
        assert_eq!(sol[&1], 135); // base yaw 0 deg = rest
    }

    #[test]
    fn far_target_is_unreachable() {
        let g = Geometry { base_height: 0.0, upper_arm: 100.0, forearm: 100.0, wrist: 0.0 };
        assert!(inverse_kinematics(&motors(), &g, 500.0, 0.0, 0.0, 0.0, false).is_none());
    }

    #[test]
    fn rounds_half_to_even_like_python() {
        assert_eq!(round_half_even(2.5), 2);
        assert_eq!(round_half_even(3.5), 4);
        assert_eq!(round_half_even(-2.5), -2);
    }
}
