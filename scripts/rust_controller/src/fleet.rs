//! Fleet mode: bridges RIFT's HTTP protocol (https://github.com/CursedPrograms/RIFT)
//! to the shared angles, which the UI tick reads each frame and sends over
//! serial like any other mode. Also serves the scripts/web/ control page, so the
//! arm can be driven from any browser on the network. Same endpoints and wire
//! protocol as controller.py's Flask app and the C++ controller's fleet_server.cpp.

use crate::config::{web_dir, Motors};
use crate::shared::{lock, SharedState};
use serde_json::{json, Map, Value};
use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;
use tiny_http::{Header, Response, Server};

const FLEET_NAME: &str = "ARM";
const FLEET_TYPE: &str = "robot";
const FLEET_CAPABILITIES: &str = "servo_control,6dof,arm";
pub const DEFAULT_PORT: u16 = 5011;
/// Must stay under RIFT's FLEET_TTL_SECS (20s).
const HEARTBEAT: Duration = Duration::from_secs(10);

pub struct FleetServer {
    server: Arc<Server>,
    stop: Arc<AtomicBool>,
}

/// Best-effort LAN IP, so the UI can show an address RIFT (on another device) can reach.
pub fn local_lan_ip() -> String {
    std::net::UdpSocket::bind("0.0.0.0:0")
        .and_then(|s| {
            s.connect("8.8.8.8:80")?; // UDP connect: no traffic is actually sent
            s.local_addr()
        })
        .map(|a| a.ip().to_string())
        .unwrap_or_else(|_| "127.0.0.1".into())
}

impl FleetServer {
    pub fn start(
        motors: Arc<Motors>,
        shared: SharedState,
        serial_connected: Arc<AtomicBool>,
        port: u16,
        register: bool,
        rift_host: String,
        rift_port: u16,
    ) -> Result<Self, String> {
        let server = Server::http(("0.0.0.0", port))
            .map_err(|e| format!("Could not start Fleet server on port {port} (already in use?): {e}"))?;
        let server = Arc::new(server);
        let stop = Arc::new(AtomicBool::new(false));

        {
            let server = server.clone();
            std::thread::spawn(move || {
                for request in server.incoming_requests() {
                    let (motors, shared, connected) = (motors.clone(), shared.clone(), serial_connected.clone());
                    std::thread::spawn(move || handle(request, &motors, &shared, &connected));
                }
            });
        }

        if register {
            let stop = stop.clone();
            std::thread::spawn(move || {
                let url = format!("http://{rift_host}:{rift_port}/register");
                while !stop.load(Ordering::Relaxed) {
                    // RIFT/NORA may not be reachable yet - keep retrying.
                    let _ = ureq::post(&url).timeout(Duration::from_secs(2)).send_form(&[
                        ("name", FLEET_NAME),
                        ("type", FLEET_TYPE),
                        ("capabilities", FLEET_CAPABILITIES),
                    ]);
                    let mut waited = Duration::ZERO;
                    while waited < HEARTBEAT && !stop.load(Ordering::Relaxed) {
                        std::thread::sleep(Duration::from_millis(100));
                        waited += Duration::from_millis(100);
                    }
                }
            });
        }

        Ok(Self { server, stop })
    }
}

impl Drop for FleetServer {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        self.server.unblock();
    }
}

fn parse_query(query: &str) -> HashMap<String, String> {
    query
        .split('&')
        .filter(|p| !p.is_empty())
        .map(|p| match p.split_once('=') {
            Some((k, v)) => (k.to_string(), v.to_string()),
            None => (p.to_string(), String::new()),
        })
        .collect()
}

fn header(name: &str, value: &str) -> Header {
    Header::from_bytes(name.as_bytes(), value.as_bytes()).expect("valid header")
}

fn respond_json(request: tiny_http::Request, status: u16, body: Value) {
    let response = Response::from_string(body.to_string())
        .with_status_code(status)
        .with_header(header("Content-Type", "application/json"));
    let _ = request.respond(response);
}

fn respond_file(request: tiny_http::Request, name: &str, content_type: &str) {
    match std::fs::read(web_dir().join(name)) {
        Ok(bytes) => {
            let _ = request.respond(Response::from_data(bytes).with_header(header("Content-Type", content_type)));
        }
        Err(_) => {
            let _ = request.respond(Response::from_string("Not found").with_status_code(404));
        }
    }
}

fn handle(request: tiny_http::Request, motors: &Motors, shared: &SharedState, serial_connected: &AtomicBool) {
    let url = request.url().to_string();
    let (path, query) = url.split_once('?').unwrap_or((url.as_str(), ""));
    let params = parse_query(query);

    match path {
        "/" => respond_file(request, "index.html", "text/html; charset=utf-8"),
        "/style.css" => respond_file(request, "style.css", "text/css; charset=utf-8"),
        "/app.js" => respond_file(request, "app.js", "application/javascript; charset=utf-8"),
        "/ping" => {
            let _ = request.respond(
                Response::from_string(format!("{FLEET_NAME} alive")).with_header(header("Content-Type", "text/plain")),
            );
        }
        "/status" => {
            let angles = lock(shared).angles.clone();
            let mut motors_json = Map::new();
            for (n, m) in motors {
                motors_json.insert(
                    n.to_string(),
                    json!({ "channel": m.channel, "angle": angles.get(n).copied().unwrap_or(m.rest), "min": m.min, "max": m.max }),
                );
            }
            respond_json(
                request,
                200,
                json!({ "connected": serial_connected.load(Ordering::Relaxed), "motors": motors_json }),
            );
        }
        "/cmd" => {
            let motor = params.get("motor").and_then(|v| v.parse::<i32>().ok());
            let angle = params.get("angle").and_then(|v| v.parse::<i32>().ok());
            match (motor, angle) {
                (Some(motor), Some(angle)) => match motors.get(&motor) {
                    Some(m) => {
                        let angle = angle.clamp(m.min, m.max);
                        lock(shared).angles.insert(motor, angle);
                        respond_json(request, 200, json!({ "motor": motor, "angle": angle }));
                    }
                    None => respond_json(request, 400, json!({ "error": format!("unknown motor {motor}") })),
                },
                _ => respond_json(request, 400, json!({ "error": "expected ?motor=<1-6>&angle=<degrees>" })),
            }
        }
        "/reset" => match params.get("motor") {
            Some(text) => match text.parse::<i32>().ok().and_then(|n| motors.get(&n).map(|m| (n, m))) {
                Some((n, m)) => {
                    lock(shared).angles.insert(n, m.rest);
                    respond_json(request, 200, json!({ "motor": n, "angle": m.rest }));
                }
                None => respond_json(request, 400, json!({ "error": format!("unknown motor {text}") })),
            },
            None => {
                let mut all = Map::new();
                let mut s = lock(shared);
                for (n, m) in motors {
                    s.angles.insert(*n, m.rest);
                    all.insert(n.to_string(), json!(m.rest));
                }
                drop(s);
                respond_json(request, 200, Value::Object(all));
            }
        },
        _ => {
            let _ = request.respond(Response::from_string("Not found").with_status_code(404));
        }
    }
}
