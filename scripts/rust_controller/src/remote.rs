//! Client mode (--connect URL): this controller has no serial port. A background
//! thread mirrors another controller's shared angles (GET /status) into the
//! local shared state and pushes local changes back (GET /cmd), so every
//! controller and browser pointed at the same arm stays in sync. Same behaviour
//! as controller.py's RemoteArm.

use crate::shared::{lock, SharedState};
use serde_json::Value;
use std::collections::BTreeMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

pub struct RemoteArm {
    pub connected: Arc<AtomicBool>,
    /// True once we've seen the hub's real angles at least once.
    pub synced: Arc<AtomicBool>,
    stop: Arc<AtomicBool>,
    shared: SharedState,
}

impl RemoteArm {
    pub fn start(base_url: &str, shared: SharedState) -> Result<Self, String> {
        let base = base_url.trim_end_matches('/').to_string();
        if !base.starts_with("http://") {
            return Err(format!("Bad --connect URL '{base_url}' (expected http://host:port)"));
        }
        let arm = Self {
            connected: Arc::new(AtomicBool::new(false)),
            synced: Arc::new(AtomicBool::new(false)),
            stop: Arc::new(AtomicBool::new(false)),
            shared: shared.clone(),
        };
        let (connected, synced, stop) = (arm.connected.clone(), arm.synced.clone(), arm.stop.clone());
        std::thread::spawn(move || {
            while !stop.load(Ordering::Relaxed) {
                let to_send = std::mem::take(&mut lock(&shared).pending);
                match round_trip(&base, &to_send, &shared) {
                    Ok(()) => {
                        connected.store(true, Ordering::Relaxed);
                        synced.store(true, Ordering::Relaxed);
                    }
                    Err(_) => {
                        connected.store(false, Ordering::Relaxed);
                        let mut s = lock(&shared);
                        for (n, a) in to_send {
                            s.pending.entry(n).or_insert(a); // retry next round
                        }
                    }
                }
                std::thread::sleep(Duration::from_millis(100));
            }
        });
        Ok(arm)
    }

    /// Angles (motor number -> angle) that changed locally and must be pushed to the hub.
    pub fn queue(&self, changed: &BTreeMap<i32, i32>) {
        let mut s = lock(&self.shared);
        for (&n, &a) in changed {
            s.pending.insert(n, a);
        }
    }
}

impl Drop for RemoteArm {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
    }
}

fn round_trip(base: &str, to_send: &BTreeMap<i32, i32>, shared: &SharedState) -> Result<(), String> {
    let timeout = Duration::from_secs(1);
    for (n, a) in to_send {
        ureq::get(&format!("{base}/cmd"))
            .query("motor", &n.to_string())
            .query("angle", &a.to_string())
            .timeout(timeout)
            .call()
            .map_err(|e| e.to_string())?;
    }
    let body = ureq::get(&format!("{base}/status"))
        .timeout(timeout)
        .call()
        .map_err(|e| e.to_string())?
        .into_string()
        .map_err(|e| e.to_string())?;
    let status: Value = serde_json::from_str(&body).map_err(|e| e.to_string())?;
    let motors = status.get("motors").and_then(Value::as_object).ok_or("no motors in /status")?;

    let mut s = lock(shared);
    for (key, m) in motors {
        let (Ok(n), Some(angle)) = (key.parse::<i32>(), m.get("angle").and_then(Value::as_f64)) else { continue };
        if !s.pending.contains_key(&n) {
            // don't overwrite a change we haven't sent yet
            s.angles.insert(n, angle.round() as i32);
        }
    }
    Ok(())
}
