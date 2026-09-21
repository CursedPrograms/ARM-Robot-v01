//! Rust/egui counterpart of controller.py: Joystick/Sliders/IK/Fleet modes,
//! macro record/replay, live sync with the web page, and `--connect` client
//! mode. Reads the same config.json, records to the same scripts/macros/*.json
//! and serves the same scripts/web/ page as the other controllers.
//!
//! Usage:
//!   arm_controller --list-ports
//!   arm_controller --port COM6            (Linux: --port /dev/ttyACM0)
//!   arm_controller --port COM6 --mode slider
//!   arm_controller --port COM6 --serve
//!   arm_controller --connect http://192.168.0.10:5011

mod app;
mod config;
mod fleet;
mod joystick;
mod kinematics;
mod macros;
mod options;
mod remote;
mod serial_link;
mod shared;

use eframe::egui;

fn main() -> eframe::Result<()> {
    let opts = match options::Options::parse(std::env::args().skip(1)) {
        Ok(o) => o,
        Err(e) => {
            eprintln!("{e}");
            std::process::exit(1);
        }
    };

    if opts.list_ports {
        let ports = serial_link::list_ports();
        if ports.is_empty() {
            println!("No serial ports found.");
        } else {
            println!("Available serial ports:");
            for (name, description) in ports {
                println!("  {name}  -  {description}");
            }
        }
        return Ok(());
    }
    if opts.list_joysticks {
        match joystick::describe_devices() {
            Ok(lines) if lines.is_empty() => println!("No joystick/controller devices found."),
            Ok(lines) => {
                println!("Found {} device(s):", lines.len());
                lines.iter().for_each(|l| println!("{l}"));
            }
            Err(e) => println!("No joystick/controller devices found ({e})."),
        }
        return Ok(());
    }

    let app = app::App::new(opts);
    let native_options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default().with_inner_size([620.0, 640.0]).with_title("Arm Controller (Rust)"),
        ..Default::default()
    };
    eframe::run_native("Arm Controller (Rust)", native_options, Box::new(move |_cc| Ok(Box::new(app))))
}
