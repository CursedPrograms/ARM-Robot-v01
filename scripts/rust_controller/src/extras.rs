//! extras.rs - what controller.py has beyond driving her: her VOICE (arm_voice.ps1), her arm drawn from
//! her geometry and joint maths, and the fleet's WiFi ladder (fleet_ladder.py, with --ladder).

use crate::config::{self, Geometry, Motors};
use crate::scheme::colour;
use eframe::egui::{self, pos2, vec2, Color32, Pos2, Stroke};
use std::collections::{BTreeMap, HashMap};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

pub const PANEL_W: f32 = 300.0;
const COOLDOWN: Duration = Duration::from_secs(8); // kit.Voice's: an event at most this often

#[derive(Default, Clone, PartialEq)]
struct Seen { mode: String, recording: bool, playing: bool, claw: bool }

pub struct Voice { pub on: bool, last: HashMap<String, Instant>, seen: Option<Seen> }

impl Voice {
    pub fn new() -> Self { Voice { on: true, last: HashMap::new(), seen: None } }

    fn say(&mut self, event: &str) {
        if !self.on || self.last.get(event).is_some_and(|t| t.elapsed() < COOLDOWN) { return; }
        self.last.insert(event.to_string(), Instant::now());
        let script = config::repo_root().join("scripts").join("arm_voice.ps1");
        let _ = Command::new("powershell")
            .args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File"])
            .arg(script).arg(event)
            .stdout(Stdio::null()).stderr(Stdio::null()).spawn();
    }

    /// Once a frame: says what changed, as controller.py's main loop does.
    pub fn watch(&mut self, mode: &str, recording: bool, playing: bool, claw: bool) {
        let now = Seen { mode: mode.to_string(), recording, playing, claw };
        let Some(was) = self.seen.replace(now.clone()) else { self.say("connect"); return; };
        if was.mode != now.mode { self.say(&format!("mode_{}", now.mode)); }
        if was.recording != recording { self.say(if recording { "record_on" } else { "record_off" }); }
        if was.playing != playing { self.say(if playing { "play" } else { "stop" }); }
        if was.claw != claw { self.say(if claw { "claw_close" } else { "claw_open" }); }
    }
}

/// The fleet's WiFi ladder while she runs (--ladder or FLEET_LADDER=1): fleet_ladder.py, as ARMCTL.
pub struct Ladder(Child);

impl Drop for Ladder {
    fn drop(&mut self) { let _ = self.0.kill(); }
}

pub fn start_ladder(asked: bool) -> Option<Ladder> {
    if !asked && std::env::var("FLEET_LADDER").as_deref() != Ok("1") { return None; }
    let script = config::repo_root().join("scripts").join("fleet_ladder.py");
    Command::new(if cfg!(windows) { "python" } else { "python3" })
        .arg(script).args(["ARMCTL", "--run"]).spawn().ok().map(Ladder)
}

/// Her arm, as controller.py's draw_arm(): from the side, and from above (the base turning).
pub fn draw_arm(ui: &mut egui::Ui, motors: &Motors, g: &Geometry, angles: &BTreeMap<i32, i32>) {
    let deg = |n: i32| motors.get(&n).map(|m| {
        (*angles.get(&n).unwrap_or(&m.rest) - m.rest) as f64 * m.kinematic_sign
    });
    let (Some(base), Some(sh), Some(el), Some(wr)) = (deg(1), deg(2), deg(3), deg(4)) else { return };
    let (base, sh, el, wr) = (base.to_radians(), sh.to_radians(), el.to_radians(), wr.to_radians());

    let (rect, _) = ui.allocate_exact_size(vec2(PANEL_W - 16.0, 560.0), egui::Sense::hover());
    let p = ui.painter_at(rect);
    let (w, x0, y0) = (rect.width() as f64, rect.left() as f64, rect.top() as f64);
    p.rect_filled(rect, 8.0, colour("panel"));
    let label = |at: Pos2, text: String, c: Color32| {
        p.text(at, egui::Align2::LEFT_TOP, text, egui::FontId::proportional(12.0), c);
    };
    label(pos2(rect.left() + 10.0, rect.top() + 8.0), "from the side".into(), colour("text_dim"));

    let reach = { let r = g.upper_arm + g.forearm + g.wrist; if r > 0.0 { r } else { 300.0 } };
    let s = ((w - 60.0) / reach).min(230.0 / (reach + g.base_height));
    let (ox, oy) = (x0 + 30.0, y0 + 270.0);
    let pt = |r: f64, z: f64| pos2((ox + r * s) as f32, (oy - z * s) as f32);
    p.line_segment([pos2(rect.left() + 10.0, oy as f32), pos2(rect.right() - 10.0, oy as f32)], Stroke::new(1.0f32, colour("track")));
    p.with_clip_rect(egui::Rect::from_min_size(rect.min + vec2(0.0, 24.0), vec2(rect.width(), 276.0)))
        .circle_stroke(pt(0.0, g.base_height), (reach * s) as f32, Stroke::new(1.0f32, colour("track")));

    let (a1, a2, a3) = (sh, sh + el, sh + el + wr);
    let mut j = vec![(0.0, 0.0), (0.0, g.base_height)];
    for (len, a) in [(g.upper_arm, a1), (g.forearm, a2), (g.wrist, a3)] {
        let (r, z) = j[j.len() - 1];
        j.push((r + len * a.cos(), z + len * a.sin()));
    }
    let pts: Vec<Pos2> = j.iter().map(|q| pt(q.0, q.1)).collect();
    for seg in pts.windows(2) { p.line_segment([seg[0], seg[1]], Stroke::new(6.0f32, colour("button_hover"))); }
    for q in &pts[1..4] { p.circle_filled(*q, 6.0, colour("accent")); p.circle_filled(*q, 3.0, colour("panel")); }
    let tip = pts[4];
    let open = if angles.get(&6).copied().unwrap_or(i32::MAX) < motors.get(&6).map_or(0, |m| m.rest) { 0.25 } else { 0.5 };
    for sgn in [-1.0, 1.0] {
        let a = a3 + sgn * open;
        p.line_segment([tip, tip + vec2((14.0 * a.cos()) as f32, (-14.0 * a.sin()) as f32)], Stroke::new(3.0f32, colour("accent")));
    }
    let (tr, tz) = j[4];
    label(pos2(rect.left() + 10.0, oy as f32 + 10.0), format!("tip  r {tr:.0}  z {tz:.0} mm"), colour("text"));

    let (cx, cy) = (x0 + w / 2.0, y0 + 440.0);
    label(pos2(rect.left() + 10.0, cy as f32 - 125.0), "from above".into(), colour("text_dim"));
    let c = pos2(cx as f32, cy as f32);
    p.circle_stroke(c, 100.0, Stroke::new(1.0f32, colour("track")));
    let rr = tr * 100.0 / reach;
    let t = pos2((cx + rr * base.sin()) as f32, (cy - rr * base.cos()) as f32);
    p.line_segment([c, t], Stroke::new(6.0f32, colour("button_hover")));
    p.circle_filled(c, 8.0, colour("accent"));
    p.circle_filled(t, 5.0, colour("accent"));
    label(pos2(rect.left() + 10.0, cy as f32 + 104.0), format!("base {:+.0} deg", base.to_degrees()), colour("text"));
}
