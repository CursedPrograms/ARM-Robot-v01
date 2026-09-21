//! Shared motor configuration, loaded from config.json at the repo root.
//! Rust counterpart of scripts/motor_config.py: config.json stays the single
//! source of truth for the arm's physical limits across all controllers.

use serde_json::Value;
use std::collections::BTreeMap;
use std::path::PathBuf;

#[derive(Clone, Debug)]
pub struct Motor {
    pub channel: i32,
    pub min: i32,
    pub max: i32,
    pub rest: i32,
    pub invert: bool,
    pub kinematic_sign: f64,
}

#[derive(Clone, Debug, Default)]
pub struct Geometry {
    pub base_height: f64,
    pub upper_arm: f64,
    pub forearm: f64,
    pub wrist: f64,
}

impl Geometry {
    pub fn ready(&self) -> bool {
        self.upper_arm != 0.0 && self.forearm != 0.0
    }
}

/// Motor number (1-6) -> settings, in motor order.
pub type Motors = BTreeMap<i32, Motor>;

/// Works whether launched from the repo root (the launchers) or from
/// target/release: walk up until config.json and scripts/ are found.
pub fn repo_root() -> PathBuf {
    let mut starts: Vec<PathBuf> = Vec::new();
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            starts.push(dir.to_path_buf());
        }
    }
    if let Ok(cwd) = std::env::current_dir() {
        starts.push(cwd);
    }
    for start in &starts {
        let mut dir = Some(start.as_path());
        while let Some(d) = dir {
            if d.join("config.json").is_file() && d.join("scripts").is_dir() {
                return d.to_path_buf();
            }
            dir = d.parent();
        }
    }
    std::env::current_dir().unwrap_or_default()
}

pub fn web_dir() -> PathBuf {
    repo_root().join("scripts").join("web")
}

pub fn macros_dir() -> PathBuf {
    repo_root().join("scripts").join("macros")
}

fn read_root() -> Option<Value> {
    let path = repo_root().join("config.json");
    let text = std::fs::read_to_string(&path).ok()?;
    match serde_json::from_str(&text) {
        Ok(v) => Some(v),
        Err(e) => {
            println!("Warning: could not read config.json ({e}), using defaults.");
            None
        }
    }
}

fn num(v: &Value, key: &str, default: f64) -> f64 {
    v.get(key).and_then(Value::as_f64).unwrap_or(default)
}

pub fn load_motors() -> Motors {
    let mut motors: Motors = (1..=6)
        .map(|n| {
            (
                n,
                Motor { channel: n - 1, min: 0, max: 270, rest: 135, invert: false, kinematic_sign: 1.0 },
            )
        })
        .collect();

    if let Some(overrides) = read_root().as_ref().and_then(|r| r.get("motors")).and_then(Value::as_object) {
        for (key, o) in overrides {
            let Ok(n) = key.parse::<i32>() else { continue };
            let m = motors.entry(n).or_insert(Motor {
                channel: n - 1,
                min: 0,
                max: 270,
                rest: 135,
                invert: false,
                kinematic_sign: 1.0,
            });
            m.channel = num(o, "channel", m.channel as f64).round() as i32;
            m.min = num(o, "min", m.min as f64).round() as i32;
            m.max = num(o, "max", m.max as f64).round() as i32;
            m.rest = num(o, "rest", m.rest as f64).round() as i32;
            m.invert = o.get("invert").and_then(Value::as_bool).unwrap_or(m.invert);
            m.kinematic_sign = num(o, "kinematicSign", m.kinematic_sign);
        }
    }
    motors
}

pub fn load_geometry() -> Geometry {
    let mut g = Geometry::default();
    if let Some(o) = read_root().as_ref().and_then(|r| r.get("geometry")) {
        g.base_height = num(o, "baseHeight", 0.0);
        g.upper_arm = num(o, "upperArmLength", 0.0);
        g.forearm = num(o, "forearmLength", 0.0);
        g.wrist = num(o, "wristLength", 0.0);
    }
    g
}
