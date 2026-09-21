//! The controller window: egui counterpart of controller.py and the C++
//! controller's app.cpp. Same four modes (Joystick/Sliders/IK/Fleet), same macro
//! record/replay, same wire protocol to scripts/arm/arm.ino, same shared-angle
//! sync with the web page / other controllers.
//!
//! egui is immediate-mode: `update()` draws the UI (sliders edit the plain
//! values in `slider_vals`/`ik`), then `step()` plays the role of controller.py's
//! per-frame loop body - merge this mode's input into the shared angles, then
//! send/record the shared state.

use crate::config::{self, Geometry, Motors};
use crate::fleet::{self, FleetServer};
use crate::joystick::Joystick;
use crate::kinematics;
use crate::macros::{self, MacroStep};
use crate::options::{Mode, Options};
use crate::remote::RemoteArm;
use crate::serial_link::{self, SerialLink};
use crate::shared::{lock, merge_local, Shared, SharedState};
use eframe::egui;
use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

// ---- Joystick wiring (Joystick mode only, mirrors controller.py) ----
const AXIS_MOTOR1: i32 = 0;
const AXIS_MOTOR2: i32 = 1;
const AXIS_MOTOR5: i32 = 2; // A2 and A3 move together on this stick; only A2 is read
const HAT_MOTOR3: i32 = 0;
const BUTTON_MOTOR4_BACKWARD: i32 = 2;
const BUTTON_MOTOR4_FORWARD: i32 = 3;
const BUTTON_MOTOR6_CLOSE: i32 = 0;
const DEADZONE: f64 = 0.05;

const WARN_COLOR: egui::Color32 = egui::Color32::from_rgb(240, 140, 60);

#[derive(Default)]
struct IkState {
    x: i32,
    y: i32,
    z: i32,
    pitch: i32,
    roll: i32,
    elbow_down: bool,
    claw_closed: bool,
}

pub struct App {
    opts: Options,
    motors: Arc<Motors>,
    geometry: Geometry,
    reach: i32,

    serial: Option<SerialLink>,
    serial_open: Arc<AtomicBool>,
    joystick: Option<Joystick>,
    status_base: String,
    status: String,

    mode: Mode,
    last_mode: Mode,

    shared: SharedState,
    prev_local: BTreeMap<i32, i32>, // last angle each local input produced, by motor number
    remote: Option<RemoteArm>,
    adopted: bool, // a client waits for the hub's real angles before its own inputs may write

    fleet: Option<FleetServer>,
    fleet_error: String,
    lan_ip: String,

    slider_vals: BTreeMap<i32, i32>,
    ik: IkState,
    last_valid_ik: Option<BTreeMap<i32, i32>>,
    ik_reachable: bool,
    warn: String,

    last_sent: BTreeMap<i32, i32>, // channel -> angle

    macro_files: Vec<PathBuf>,
    selected_macro: Option<usize>,
    recording: bool,
    record_steps: Vec<MacroStep>,
    record_start: Instant,
    playing: bool,
    play_steps: Vec<MacroStep>,
    play_start: Instant,
    play_index: usize,
    play_prev_mode: Mode,
}

fn axis_to_angle(value: f64, lo: i32, hi: i32) -> i32 {
    let value = if value.abs() < DEADZONE { 0.0 } else { value };
    ((value + 1.0) / 2.0 * (hi - lo) as f64 + lo as f64).round() as i32
}

impl App {
    pub fn new(opts: Options) -> Self {
        let motors = Arc::new(config::load_motors());
        let geometry = config::load_geometry();
        let reach = geometry.upper_arm + geometry.forearm + geometry.wrist;
        let reach = if reach > 0.0 { reach } else { 300.0 } as i32;

        let joystick = match Joystick::open(opts.device) {
            Ok(j) => {
                println!("Using joystick: {}", j.name);
                Some(j)
            }
            Err(e) => {
                println!("No joystick found - Joystick mode will be unavailable. ({e})");
                None
            }
        };

        let mut serial = None;
        let status_base = if let Some(url) = &opts.connect {
            format!("Remote arm at {url} (no local serial port).")
        } else {
            match opts.port.clone().or_else(serial_link::autodetect) {
                Some(port) => match SerialLink::open(&port, opts.baud) {
                    Ok(link) => {
                        serial = Some(link);
                        format!("Connected to {port} @ {} baud.", opts.baud)
                    }
                    Err(e) => format!("Could not open {port}: {e}"),
                },
                None => "No Arduino-like serial port found - display-only mode.".to_string(),
            }
        };
        println!("{status_base}");

        let angles: BTreeMap<i32, i32> = motors.iter().map(|(n, m)| (*n, m.rest)).collect();
        let shared: SharedState = Arc::new(Mutex::new(Shared { angles: angles.clone(), pending: BTreeMap::new() }));

        let remote = opts.connect.as_ref().map(|url| match RemoteArm::start(url, shared.clone()) {
            Ok(r) => r,
            Err(e) => {
                eprintln!("{e}");
                std::process::exit(1);
            }
        });

        let m5 = &motors[&5];
        let ik = IkState { z: geometry.base_height as i32, roll: m5.rest, ..Default::default() };
        let mode = opts.mode.unwrap_or(if joystick.is_some() { Mode::Joystick } else { Mode::Slider });

        let mut app = Self {
            adopted: remote.is_none(),
            remote,
            serial_open: Arc::new(AtomicBool::new(serial.is_some())),
            serial,
            joystick,
            status: status_base.clone(),
            status_base,
            mode,
            last_mode: mode,
            shared,
            prev_local: BTreeMap::new(),
            fleet: None,
            fleet_error: String::new(),
            lan_ip: fleet::local_lan_ip(),
            slider_vals: angles,
            ik,
            last_valid_ik: None,
            ik_reachable: true,
            warn: String::new(),
            last_sent: BTreeMap::new(),
            macro_files: macros::list(),
            selected_macro: None,
            recording: false,
            record_steps: Vec::new(),
            record_start: Instant::now(),
            playing: false,
            play_steps: Vec::new(),
            play_start: Instant::now(),
            play_index: 0,
            play_prev_mode: mode,
            motors,
            geometry,
            reach,
            opts,
        };
        app.selected_macro = if app.macro_files.is_empty() { None } else { Some(0) };
        if app.mode == Mode::Fleet || app.opts.serve {
            app.ensure_fleet_started();
        }
        app
    }

    fn ensure_fleet_started(&mut self) {
        if self.fleet.is_some() || !self.fleet_error.is_empty() || self.opts.connect.is_some() {
            return; // a client has no arm of its own to serve
        }
        match FleetServer::start(
            self.motors.clone(),
            self.shared.clone(),
            self.serial_open.clone(),
            self.opts.fleet_port,
            !self.opts.no_register,
            self.opts.rift_host.clone(),
            self.opts.rift_port,
        ) {
            Ok(server) => {
                self.fleet = Some(server);
                let url = format!("http://{}:{}", self.lan_ip, self.opts.fleet_port);
                println!("Web control on {url}");
                self.status_base = format!("{}  |  Web: {url}", self.status_base);
            }
            Err(e) => {
                println!("{e}");
                self.fleet_error = e;
            }
        }
    }

    // =====================================================================
    // Shared-angle sync
    // =====================================================================

    fn to_motor_keyed(&self, by_channel: &BTreeMap<i32, i32>) -> BTreeMap<i32, i32> {
        self.motors.iter().filter_map(|(n, m)| by_channel.get(&m.channel).map(|a| (*n, *a))).collect()
    }

    fn shared_as_channel_map(&self) -> BTreeMap<i32, i32> {
        let s = lock(&self.shared);
        self.motors.iter().map(|(n, m)| (m.channel, s.angles.get(n).copied().unwrap_or(m.rest))).collect()
    }

    /// Writes channel-keyed angles into the shared state (used by macro playback).
    fn publish_by_channel(&self, by_channel: &BTreeMap<i32, i32>) -> BTreeMap<i32, i32> {
        let changed = self.to_motor_keyed(by_channel);
        let mut s = lock(&self.shared);
        for (n, a) in &changed {
            s.angles.insert(*n, *a);
        }
        changed
    }

    /// Slider positions adopt the shared angles (so web-page/other-input changes show up).
    fn follow_sliders(&mut self) {
        let s = lock(&self.shared);
        for (n, v) in self.slider_vals.iter_mut() {
            if let Some(a) = s.angles.get(n) {
                *v = *a;
                self.prev_local.insert(*n, *a);
            }
        }
    }

    fn send(&mut self, commands: &BTreeMap<i32, i32>) {
        if *commands == self.last_sent {
            return;
        }
        let line = commands.iter().map(|(ch, a)| format!("{ch}:{a}")).collect::<Vec<_>>().join(",");
        if let Some(serial) = &mut self.serial {
            serial.write_line(&line);
        }
        self.last_sent = commands.clone();
    }

    // =====================================================================
    // Per-frame update (controller.py's main loop body)
    // =====================================================================

    fn joystick_commands(&self) -> BTreeMap<i32, i32> {
        let js = self.joystick.as_ref().expect("checked by caller");
        js.update();
        let m = &self.motors;

        let (mut m1, mut m2, mut m5) = (js.axis(AXIS_MOTOR1), js.axis(AXIS_MOTOR2), js.axis(AXIS_MOTOR5));
        let mut m3 = js.hat_y(HAT_MOTOR3) as f64;
        let (forward, backward) = (js.button(BUTTON_MOTOR4_FORWARD), js.button(BUTTON_MOTOR4_BACKWARD));
        let mut m4 = if forward && !backward {
            1.0
        } else if backward && !forward {
            -1.0
        } else {
            0.0
        };
        let mut close = js.button(BUTTON_MOTOR6_CLOSE);
        if m[&6].invert {
            close = !close;
        }
        let inv = |n: i32, v: f64| if m[&n].invert { -v } else { v };
        (m1, m2, m3, m4, m5) = (inv(1, m1), inv(2, m2), inv(3, m3), inv(4, m4), inv(5, m5));

        BTreeMap::from([
            (m[&1].channel, axis_to_angle(m1, m[&1].min, m[&1].max)),
            (m[&2].channel, axis_to_angle(m2, m[&2].min, m[&2].max)),
            (m[&3].channel, axis_to_angle(m3, m[&3].min, m[&3].max)),
            (m[&4].channel, axis_to_angle(m4, m[&4].min, m[&4].max)),
            (m[&5].channel, axis_to_angle(m5, m[&5].min, m[&5].max)),
            (m[&6].channel, if close { m[&6].max } else { m[&6].min }),
        ])
    }

    fn step(&mut self) {
        if let Some(remote) = &self.remote {
            self.status = format!(
                "Remote arm {}: {}",
                self.opts.connect.as_deref().unwrap_or(""),
                if remote.connected.load(Ordering::Relaxed) { "connected" } else { "UNREACHABLE" }
            );
        } else {
            self.status = self.status_base.clone();
        }

        if self.playing {
            let elapsed = self.play_start.elapsed().as_secs_f64();
            while self.play_index < self.play_steps.len() && self.play_steps[self.play_index].t <= elapsed {
                let commands = self.play_steps[self.play_index].commands.clone();
                self.send(&commands);
                let changed = self.publish_by_channel(&commands);
                if let Some(remote) = &self.remote {
                    remote.queue(&changed);
                }
                self.play_index += 1;
            }
            if self.mode == Mode::Slider {
                self.follow_sliders();
            }
            if self.play_index >= self.play_steps.len() {
                self.stop_playback();
            }
            return;
        }

        if self.mode != self.last_mode {
            self.prev_local.clear();
            if self.mode == Mode::Slider {
                self.follow_sliders();
            }
            self.last_mode = self.mode;
        }

        let mut local: Option<BTreeMap<i32, i32>> = None; // channel -> angle from this mode's own input, if any
        self.warn.clear();

        match self.mode {
            Mode::Joystick => {
                if self.joystick.is_some() {
                    local = Some(self.joystick_commands());
                } else {
                    self.warn = "No joystick connected.".into();
                }
            }
            Mode::Slider => {
                local = Some(self.motors.iter().map(|(n, m)| (m.channel, self.slider_vals[n])).collect());
            }
            Mode::Ik => {
                if !self.geometry.ready() {
                    self.warn = "Geometry not measured - fill in config.json's \"geometry\" section.".into();
                } else {
                    let ik = &self.ik;
                    let solution = kinematics::inverse_kinematics(
                        &self.motors,
                        &self.geometry,
                        ik.x as f64,
                        ik.y as f64,
                        ik.z as f64,
                        ik.pitch as f64,
                        ik.elbow_down,
                    );
                    match solution {
                        Some(sol) => {
                            self.ik_reachable = true;
                            let mut cmd: BTreeMap<i32, i32> =
                                sol.iter().map(|(n, a)| (self.motors[n].channel, *a)).collect();
                            cmd.insert(self.motors[&5].channel, ik.roll);
                            let claw = &self.motors[&6];
                            cmd.insert(claw.channel, if ik.claw_closed { claw.max } else { claw.min });
                            self.last_valid_ik = Some(cmd.clone());
                            local = Some(cmd);
                        }
                        None => {
                            self.ik_reachable = false;
                            local = self.last_valid_ik.clone(); // hold the last good pose
                            self.warn = "Target unreachable - holding last valid pose.".into();
                        }
                    }
                }
            }
            Mode::Fleet => {
                self.warn = if !self.fleet_error.is_empty() {
                    self.fleet_error.clone()
                } else if self.opts.connect.is_some() {
                    "Showing the remote arm's angles.".into()
                } else {
                    let mut text = format!("Open http://{}:{} in a browser to control", self.lan_ip, self.opts.fleet_port);
                    if !self.opts.no_register {
                        text += &format!("  -  heartbeating to RIFT at {}:{}", self.opts.rift_host, self.opts.rift_port);
                    }
                    text
                };
            }
        }

        // Merge this mode's input into the shared angles, then always send/record the
        // shared state (so web-page and RIFT changes reach the arm in any mode).
        if let Some(local) = local {
            let local_by_motor = self.to_motor_keyed(&local);
            if !self.adopted {
                let synced = self.remote.as_ref().is_some_and(|r| r.synced.load(Ordering::Relaxed));
                if synced {
                    // connected: take the hub's state as-is, don't move the arm
                    self.prev_local = local_by_motor;
                    self.adopted = true;
                }
            } else {
                let changed = {
                    let mut s = lock(&self.shared);
                    merge_local(&mut s.angles, &mut self.prev_local, &local_by_motor)
                };
                if let Some(remote) = &self.remote {
                    if !changed.is_empty() {
                        remote.queue(&changed);
                    }
                }
            }
            if self.mode == Mode::Slider {
                self.follow_sliders();
            }
        }

        let commands = self.shared_as_channel_map();
        self.send(&commands);
        if self.recording {
            self.record_steps
                .push(MacroStep { t: self.record_start.elapsed().as_secs_f64(), commands: commands.clone() });
        }
    }

    // =====================================================================
    // Macros
    // =====================================================================

    fn toggle_record(&mut self) {
        if self.playing {
            return;
        }
        if !self.recording {
            self.recording = true;
            self.record_steps.clear();
            self.record_start = Instant::now();
            return;
        }
        self.recording = false;
        if self.record_steps.is_empty() {
            return;
        }
        match macros::save(&self.record_steps) {
            Ok(path) => {
                println!(
                    "Saved macro: {} ({} steps)",
                    path.file_name().unwrap_or_default().to_string_lossy(),
                    self.record_steps.len()
                );
                self.macro_files = macros::list();
                self.selected_macro = Some(0);
            }
            Err(e) => self.status_base = format!("Could not save macro: {e}"),
        }
    }

    fn toggle_play(&mut self) {
        if self.playing {
            self.stop_playback();
            return;
        }
        let Some(path) = self.selected_macro.and_then(|i| self.macro_files.get(i)) else { return };
        match macros::load(path) {
            Ok(steps) => {
                self.play_steps = steps;
                self.play_index = 0;
                self.play_prev_mode = self.mode;
                self.play_start = Instant::now();
                self.playing = true;
            }
            Err(e) => self.status_base = format!("Could not load macro: {e}"),
        }
    }

    fn stop_playback(&mut self) {
        self.playing = false;
        self.mode = self.play_prev_mode;
        if self.mode == Mode::Fleet {
            self.ensure_fleet_started();
        }
    }

    // =====================================================================
    // UI
    // =====================================================================

    fn draw(&mut self, ui: &mut egui::Ui) {
        ui.heading("Arm Controller (Rust)");
        ui.label(egui::RichText::new(&self.status).small().weak());
        ui.add_space(4.0);

        let mut clicked_mode = None;
        ui.horizontal(|ui| {
            for (mode, name) in [(Mode::Joystick, "Joystick"), (Mode::Slider, "Sliders"), (Mode::Ik, "IK"), (Mode::Fleet, "Fleet")] {
                let enabled = !self.playing && (mode != Mode::Joystick || self.joystick.is_some());
                let button = egui::Button::new(name).selected(self.mode == mode).min_size(egui::vec2(110.0, 30.0));
                if ui.add_enabled(enabled, button).clicked() {
                    clicked_mode = Some(mode);
                }
            }
        });
        if let Some(mode) = clicked_mode {
            self.mode = mode;
            if mode == Mode::Fleet {
                self.ensure_fleet_started();
            }
        }

        ui.add_space(4.0);
        let (mut record_clicked, mut play_clicked) = (false, false);
        ui.horizontal(|ui| {
            let record_label = if self.recording {
                format!("Recording... {:.1}s", self.record_start.elapsed().as_secs_f64())
            } else {
                "Record".to_string()
            };
            let mut record = egui::Button::new(record_label).min_size(egui::vec2(150.0, 28.0));
            if self.recording {
                record = record.fill(egui::Color32::from_rgb(150, 50, 50));
            }
            record_clicked = ui.add_enabled(!self.playing, record).clicked();

            let play_label = if self.playing { format!("Stop {}/{}", self.play_index, self.play_steps.len()) } else { "Play".to_string() };
            play_clicked = ui
                .add(egui::Button::new(play_label).selected(self.playing).min_size(egui::vec2(150.0, 28.0)))
                .clicked();
        });
        if record_clicked {
            self.toggle_record();
        }
        if play_clicked {
            self.toggle_play();
        }

        egui::ScrollArea::vertical().id_salt("macros").max_height(76.0).show(ui, |ui| {
            if self.macro_files.is_empty() {
                ui.weak("No macros recorded yet.");
            }
            for (i, path) in self.macro_files.iter().enumerate() {
                let name = path.file_stem().unwrap_or_default().to_string_lossy();
                let label = format!("{}. {name}", i + 1);
                if ui.selectable_label(self.selected_macro == Some(i), label).clicked() && !self.playing {
                    self.selected_macro = Some(i);
                }
            }
        });

        ui.add_space(6.0);
        if !self.warn.is_empty() {
            ui.colored_label(WARN_COLOR, &self.warn);
        }
        ui.spacing_mut().slider_width = 320.0;

        match self.mode {
            Mode::Slider => {
                for (n, m) in self.motors.iter() {
                    ui.horizontal(|ui| {
                        ui.label(format!("Motor {n} (ch {}, {}-{})", m.channel, m.min, m.max));
                        if let Some(v) = self.slider_vals.get_mut(n) {
                            ui.add(egui::Slider::new(v, m.min..=m.max).suffix("\u{00B0}"));
                        }
                    });
                }
            }
            Mode::Ik if self.geometry.ready() => {
                let reach = self.reach;
                let (roll_min, roll_max) = (self.motors[&5].min, self.motors[&5].max);
                ui.horizontal(|ui| {
                    ui.label("Target X (mm)");
                    ui.add(egui::Slider::new(&mut self.ik.x, -reach..=reach));
                });
                ui.horizontal(|ui| {
                    ui.label("Target Y (mm)");
                    ui.add(egui::Slider::new(&mut self.ik.y, -reach..=reach));
                });
                ui.horizontal(|ui| {
                    ui.label("Target Z (mm)");
                    ui.add(egui::Slider::new(&mut self.ik.z, 0..=reach));
                });
                ui.horizontal(|ui| {
                    ui.label("Pitch (deg)");
                    ui.add(egui::Slider::new(&mut self.ik.pitch, -90..=90));
                });
                ui.horizontal(|ui| {
                    ui.label("Roll (motor 5)");
                    ui.add(egui::Slider::new(&mut self.ik.roll, roll_min..=roll_max));
                });
                ui.horizontal(|ui| {
                    if ui.button(if self.ik.elbow_down { "Elbow: Down" } else { "Elbow: Up" }).clicked() {
                        self.ik.elbow_down = !self.ik.elbow_down;
                    }
                    if ui.button(if self.ik.claw_closed { "Claw: Closed" } else { "Claw: Open" }).clicked() {
                        self.ik.claw_closed = !self.ik.claw_closed;
                    }
                });
            }
            Mode::Joystick | Mode::Fleet => {
                for (n, m) in self.motors.iter() {
                    let angle = self.last_sent.get(&m.channel).copied().unwrap_or(0);
                    ui.label(egui::RichText::new(format!("Motor {n} (ch {}): {angle}", m.channel)).size(16.0));
                }
            }
            Mode::Ik => {}
        }
    }
}

impl eframe::App for App {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        if ctx.input(|i| i.key_pressed(egui::Key::Escape)) {
            ctx.send_viewport_cmd(egui::ViewportCommand::Close);
        }
        if !self.playing {
            let keys = [
                egui::Key::Num1,
                egui::Key::Num2,
                egui::Key::Num3,
                egui::Key::Num4,
                egui::Key::Num5,
                egui::Key::Num6,
                egui::Key::Num7,
                egui::Key::Num8,
                egui::Key::Num9,
            ];
            for (i, key) in keys.iter().enumerate() {
                if i < self.macro_files.len() && ctx.input(|inp| inp.key_pressed(*key)) {
                    self.selected_macro = Some(i);
                }
            }
        }

        egui::CentralPanel::default().show(ctx, |ui| self.draw(ui));
        self.step();

        let rate = if self.opts.rate > 0.0 { self.opts.rate } else { 30.0 };
        ctx.request_repaint_after(Duration::from_secs_f64(1.0 / rate));
    }
}
