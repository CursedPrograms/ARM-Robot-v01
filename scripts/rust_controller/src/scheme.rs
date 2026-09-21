//! UI colours from colour_scheme.xml at the repo root, shared by every
//! controller. Edit that file and restart - no rebuild. Any role missing from
//! it (or the whole file being unreadable) falls back to DEFAULTS.

use crate::config::repo_root;
use eframe::egui::{self, Color32};
use std::collections::HashMap;
use std::sync::OnceLock;

const DEFAULTS: [(&str, &str); 16] = [
    ("background", "#33292F"),
    ("panel", "#331F2B"),
    ("border", "#361529"),
    ("text", "#FFFFFF"),
    ("text_dim", "#C9B6C1"),
    ("button", "#361529"),
    ("button_hover", "#691548"),
    ("button_active", "#9C0060"),
    ("button_disabled", "#331F2B"),
    ("accent", "#9C0060"),
    ("accent_hover", "#C21F82"),
    ("track", "#691548"),
    ("selected", "#691548"),
    ("danger", "#963232"),
    ("danger_hover", "#AD3A3A"),
    ("warn", "#F08C3C"),
];

fn parse_hex(value: &str) -> Option<Color32> {
    let hex = value.trim().trim_start_matches('#');
    if hex.len() != 6 {
        return None;
    }
    let n = u32::from_str_radix(hex, 16).ok()?;
    Some(Color32::from_rgb((n >> 16) as u8, (n >> 8) as u8, n as u8))
}

/// Pulls (name, value) out of a `<colour name="..." value="..."/>` line.
fn parse_line(line: &str) -> Option<(&str, &str)> {
    let rest = &line[line.find("<colour ")?..];
    let name_start = rest.find("name=\"")? + 6;
    let name_end = name_start + rest[name_start..].find('"')?;
    let value_start = name_end + rest[name_end..].find("value=\"")? + 7;
    let value_end = value_start + rest[value_start..].find('"')?;
    Some((&rest[name_start..name_end], &rest[value_start..value_end]))
}

fn table() -> &'static HashMap<String, Color32> {
    static TABLE: OnceLock<HashMap<String, Color32>> = OnceLock::new();
    TABLE.get_or_init(|| {
        let mut map: HashMap<String, Color32> = DEFAULTS
            .iter()
            .filter_map(|(name, value)| Some((name.to_string(), parse_hex(value)?)))
            .collect();
        match std::fs::read_to_string(repo_root().join("colour_scheme.xml")) {
            Ok(text) => {
                for line in text.lines() {
                    if let Some((name, value)) = parse_line(line) {
                        match parse_hex(value) {
                            Some(c) => {
                                map.insert(name.to_string(), c);
                            }
                            None => eprintln!("Warning: colour_scheme.xml: bad value for '{name}', keeping default."),
                        }
                    }
                }
            }
            Err(e) => eprintln!("Warning: could not read colour_scheme.xml ({e}), using default colours."),
        }
        map
    })
}

/// The colour for a role such as "background" or "warn".
pub fn colour(name: &str) -> Color32 {
    table().get(name).copied().unwrap_or(Color32::MAGENTA)
}

/// Restyles egui's dark theme with the scheme.
pub fn apply(ctx: &egui::Context) {
    let mut v = egui::Visuals::dark();
    v.panel_fill = colour("background");
    v.window_fill = colour("panel");
    v.extreme_bg_color = colour("panel");
    v.override_text_color = Some(colour("text"));
    v.weak_text_color = Some(colour("text_dim"));
    v.selection.bg_fill = colour("accent");
    v.hyperlink_color = colour("accent_hover");

    v.widgets.noninteractive.bg_fill = colour("panel");
    v.widgets.noninteractive.weak_bg_fill = colour("panel");
    v.widgets.noninteractive.bg_stroke.color = colour("border");

    v.widgets.inactive.bg_fill = colour("track");
    v.widgets.inactive.weak_bg_fill = colour("button");
    v.widgets.hovered.bg_fill = colour("accent_hover");
    v.widgets.hovered.weak_bg_fill = colour("button_hover");
    v.widgets.active.bg_fill = colour("accent");
    v.widgets.active.weak_bg_fill = colour("button_active");
    v.widgets.open.weak_bg_fill = colour("button_active");
    ctx.set_visuals(v);
}
