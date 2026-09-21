//! USB serial link to the Arduino running scripts/arm/arm.ino. Wire protocol is
//! the same as every other controller: "channel:angle,channel:angle,...\n".

use serialport::{SerialPort, SerialPortType};
use std::io::Write;
use std::time::Duration;

/// Descriptions that identify likely Arduino USB-serial adapters, for --port auto-detect.
const ARDUINO_HINTS: [&str; 5] = ["arduino", "ch340", "usb-serial", "cp210", "ftdi"];
/// USB vendor ids of the same adapters (Arduino, CH340, CP210x, FTDI).
const ARDUINO_VIDS: [u16; 5] = [0x2341, 0x2A03, 0x1A86, 0x10C4, 0x0403];

pub struct SerialLink {
    port: Box<dyn SerialPort>,
}

impl SerialLink {
    pub fn open(name: &str, baud: u32) -> Result<Self, String> {
        let mut port = serialport::new(name, baud)
            .timeout(Duration::from_millis(200))
            .open()
            .map_err(|e| e.to_string())?;
        let _ = port.write_data_terminal_ready(true); // same as pyserial's default: resets the Arduino on connect
        std::thread::sleep(Duration::from_secs(2)); // give the Arduino time to reset
        Ok(Self { port })
    }

    pub fn write_line(&mut self, line: &str) {
        // A stalled or unplugged device just drops this update; the next frame retries.
        let _ = self.port.write_all(format!("{line}\n").as_bytes());
    }
}

/// (port name, human description)
pub fn list_ports() -> Vec<(String, String)> {
    serialport::available_ports()
        .unwrap_or_default()
        .into_iter()
        .map(|p| {
            let description = match &p.port_type {
                SerialPortType::UsbPort(u) => format!(
                    "{} {}",
                    u.manufacturer.clone().unwrap_or_default(),
                    u.product.clone().unwrap_or_else(|| format!("USB {:04x}:{:04x}", u.vid, u.pid))
                )
                .trim()
                .to_string(),
                SerialPortType::PciPort => "PCI".to_string(),
                SerialPortType::BluetoothPort => "Bluetooth".to_string(),
                SerialPortType::Unknown => "Unknown".to_string(),
            };
            (p.port_name, description)
        })
        .collect()
}

pub fn autodetect() -> Option<String> {
    for p in serialport::available_ports().unwrap_or_default() {
        if let SerialPortType::UsbPort(u) = &p.port_type {
            let text = format!(
                "{} {}",
                u.manufacturer.clone().unwrap_or_default(),
                u.product.clone().unwrap_or_default()
            )
            .to_lowercase();
            if ARDUINO_VIDS.contains(&u.vid) || ARDUINO_HINTS.iter().any(|h| text.contains(h)) {
                return Some(p.port_name);
            }
        }
    }
    None
}
