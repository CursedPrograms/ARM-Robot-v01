//! Shared arm state. `Shared::angles` is the single set of motor angles every
//! input (window sliders, joystick, IK, the web page, RIFT, remote clients)
//! writes to and every output (serial, the sliders, the web page) reads from.
//!
//! The sync rule: an input whose value changed since last frame writes it
//! (last writer wins); inputs that didn't change leave what another input
//! wrote alone and instead follow it. All maps are keyed by motor number.

use std::collections::BTreeMap;
use std::sync::{Arc, Mutex, MutexGuard};

#[derive(Default)]
pub struct Shared {
    pub angles: BTreeMap<i32, i32>,
    /// Client mode only: local changes not yet pushed to the hub.
    pub pending: BTreeMap<i32, i32>,
}

pub type SharedState = Arc<Mutex<Shared>>;

pub fn lock(state: &SharedState) -> MutexGuard<'_, Shared> {
    // A panic elsewhere shouldn't take the whole arm down with a poisoned lock.
    state.lock().unwrap_or_else(|e| e.into_inner())
}

/// Writes every entry of `local` that differs from `prev_local` into `shared`,
/// remembers `local` for next frame, and returns what it changed.
pub fn merge_local(
    shared: &mut BTreeMap<i32, i32>,
    prev_local: &mut BTreeMap<i32, i32>,
    local: &BTreeMap<i32, i32>,
) -> BTreeMap<i32, i32> {
    let mut changed = BTreeMap::new();
    for (&n, &angle) in local {
        if prev_local.get(&n) != Some(&angle) {
            shared.insert(n, angle);
            changed.insert(n, angle);
        }
    }
    *prev_local = local.clone();
    changed
}

#[cfg(test)]
mod tests {
    use super::*;

    fn map(pairs: &[(i32, i32)]) -> BTreeMap<i32, i32> {
        pairs.iter().copied().collect()
    }

    #[test]
    fn first_frame_writes_everything() {
        let mut shared = map(&[(1, 135), (2, 50)]);
        let mut prev = BTreeMap::new();
        let changed = merge_local(&mut shared, &mut prev, &map(&[(1, 100), (2, 50)]));
        assert_eq!(shared, map(&[(1, 100), (2, 50)]));
        assert_eq!(changed, map(&[(1, 100), (2, 50)]));
    }

    #[test]
    fn untouched_inputs_leave_remote_changes_alone() {
        let mut shared = map(&[(1, 135), (2, 50)]);
        let mut prev = map(&[(1, 135), (2, 50)]);
        shared.insert(1, 140); // the phone moves motor 1
        let changed = merge_local(&mut shared, &mut prev, &map(&[(1, 135), (2, 50)]));
        assert_eq!(shared[&1], 140);
        assert!(changed.is_empty());
    }

    #[test]
    fn a_moved_input_wins() {
        let mut shared = map(&[(1, 140), (2, 50)]);
        let mut prev = map(&[(1, 135), (2, 50)]);
        let changed = merge_local(&mut shared, &mut prev, &map(&[(1, 135), (2, 80)]));
        assert_eq!(shared, map(&[(1, 140), (2, 80)])); // motor 2 moved locally, motor 1 stays remote
        assert_eq!(changed, map(&[(2, 80)]));
    }
}
