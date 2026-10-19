//! Every key and joystick input in its own window (F1), the Rust counterpart of
//! scripts/keymap.py's window. It shows scripts/keymap.json, which keymap.py
//! writes (python scripts/keymap.py --json scripts/keymap.json).

use crate::config;
use crate::scheme::colour;
use eframe::egui;

pub struct Keymap {
    title: String,
    sections: Vec<(String, Vec<(String, String)>)>, // (heading, [(key, does)]); an empty key is a note
}

/// Read again each time the window opens, so a fresh keymap.json shows without a restart.
pub fn load() -> Keymap {
    let path = config::repo_root().join("scripts").join("keymap.json");
    let parsed = std::fs::read_to_string(&path)
        .map_err(|e| e.to_string())
        .and_then(|text| serde_json::from_str::<serde_json::Value>(&text).map_err(|e| e.to_string()));
    let text = |v: &serde_json::Value| v.as_str().unwrap_or("").to_string();
    match parsed {
        Ok(root) => Keymap {
            title: root["title"].as_str().unwrap_or("ARM - controls").to_string(),
            sections: root["sections"]
                .as_array()
                .into_iter()
                .flatten()
                .map(|s| {
                    let rows = s["keys"].as_array().into_iter().flatten().map(|r| (text(&r[0]), text(&r[1]))).collect();
                    (text(&s["title"]), rows)
                })
                .collect(),
        },
        Err(e) => Keymap {
            title: "ARM - controls".into(),
            sections: vec![(
                "keymap.json not readable".into(),
                vec![(String::new(), e), (String::new(), "run: python scripts/keymap.py --json scripts/keymap.json".into())],
            )],
        },
    }
}

/// Shows the window for one frame; returns false once it should close (Esc, F1 or its close button).
pub fn show(ctx: &egui::Context, keymap: &Keymap) -> bool {
    let mut open = true;
    ctx.show_viewport_immediate(
        egui::ViewportId::from_hash_of("arm_keys"),
        egui::ViewportBuilder::default().with_title(&keymap.title).with_inner_size([580.0, 760.0]),
        |ctx, _class| {
            if ctx.input(|i| i.viewport().close_requested() || i.key_pressed(egui::Key::Escape) || i.key_pressed(egui::Key::F1)) {
                open = false;
            }
            egui::CentralPanel::default().show(ctx, |ui| {
                egui::ScrollArea::vertical().show(ui, |ui| draw(ui, keymap));
            });
        },
    );
    open
}

fn draw(ui: &mut egui::Ui, keymap: &Keymap) {
    let mono = |size: f32| egui::FontId::monospace(size);
    ui.label(egui::RichText::new(keymap.title.to_uppercase()).font(mono(18.0)).strong().color(colour("accent")));
    for (heading, rows) in &keymap.sections {
        ui.add_space(12.0);
        ui.label(egui::RichText::new(heading).font(mono(14.0)).strong().color(colour("accent")));
        egui::Frame::none().fill(colour("panel")).inner_margin(6.0).show(ui, |ui| {
            ui.set_width(ui.available_width());
            ui.spacing_mut().item_spacing.y = 4.0;
            for (key, does) in rows {
                if key.is_empty() {
                    // A row without a key is a note across the table.
                    ui.add(egui::Label::new(egui::RichText::new(does).font(mono(11.0)).italics().color(colour("text_dim"))).wrap());
                    continue;
                }
                ui.horizontal_top(|ui| {
                    let k = egui::Label::new(egui::RichText::new(key).font(mono(12.0)).strong().color(colour("text"))).wrap();
                    ui.allocate_ui_with_layout(egui::vec2(150.0, 0.0), egui::Layout::top_down(egui::Align::LEFT), |ui| {
                        ui.set_width(150.0);
                        ui.add(k);
                    });
                    ui.add(egui::Label::new(egui::RichText::new(does).font(mono(12.0)).color(colour("text"))).wrap());
                });
            }
        });
    }
}
