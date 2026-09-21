//! Record/replay motor-pose macros as JSON. Rust counterpart of controller.py's
//! macro helpers; reads/writes the same scripts/macros/*.json files as every
//! other controller.

use crate::config::macros_dir;
use serde_json::{json, Map, Value};
use std::collections::BTreeMap;
use std::path::PathBuf;

#[derive(Clone, Debug)]
pub struct MacroStep {
    pub t: f64,
    /// channel -> angle
    pub commands: BTreeMap<i32, i32>,
}

/// Newest first (file names embed the timestamp).
pub fn list() -> Vec<PathBuf> {
    let Ok(entries) = std::fs::read_dir(macros_dir()) else { return Vec::new() };
    let mut files: Vec<PathBuf> = entries
        .filter_map(Result::ok)
        .map(|e| e.path())
        .filter(|p| p.extension().is_some_and(|x| x == "json"))
        .collect();
    files.sort_by(|a, b| b.file_name().cmp(&a.file_name()));
    files
}

pub fn save(steps: &[MacroStep]) -> std::io::Result<PathBuf> {
    std::fs::create_dir_all(macros_dir())?;
    let now = chrono::Local::now();
    let path = macros_dir().join(format!("macro_{}.json", now.format("%Y%m%d_%H%M%S")));

    let steps_json: Vec<Value> = steps
        .iter()
        .map(|s| {
            let commands: Map<String, Value> = s.commands.iter().map(|(ch, a)| (ch.to_string(), json!(a))).collect();
            json!({ "t": s.t, "commands": commands })
        })
        .collect();
    let root = json!({ "created": now.format("%Y-%m-%d %H:%M:%S").to_string(), "steps": steps_json });
    std::fs::write(&path, root.to_string())?;
    Ok(path)
}

pub fn load(path: &PathBuf) -> Result<Vec<MacroStep>, String> {
    let text = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    let root: Value = serde_json::from_str(&text).map_err(|e| e.to_string())?;
    let mut steps = Vec::new();
    for s in root.get("steps").and_then(Value::as_array).into_iter().flatten() {
        let t = s.get("t").and_then(Value::as_f64).unwrap_or(0.0);
        let mut commands = BTreeMap::new();
        for (ch, a) in s.get("commands").and_then(Value::as_object).into_iter().flatten() {
            if let (Ok(ch), Some(a)) = (ch.parse::<i32>(), a.as_f64()) {
                commands.insert(ch, a.round() as i32);
            }
        }
        steps.push(MacroStep { t, commands });
    }
    Ok(steps)
}
