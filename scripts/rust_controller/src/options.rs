//! Command-line options, same flags as controller.py / the other controllers.

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Mode {
    Joystick,
    Slider,
    Ik,
    Fleet,
}

#[derive(Clone, Debug)]
pub struct Options {
    pub device: i32,
    pub port: Option<String>,
    pub baud: u32,
    pub rate: f64,
    pub mode: Option<Mode>,
    pub list_joysticks: bool,
    pub list_ports: bool,
    pub fleet_port: u16,
    pub rift_host: String,
    pub rift_port: u16,
    pub no_register: bool,
    pub serve: bool,
    pub connect: Option<String>,
}

impl Default for Options {
    fn default() -> Self {
        Self {
            device: 0,
            port: None,
            baud: 115200,
            rate: 30.0,
            mode: None,
            list_joysticks: false,
            list_ports: false,
            fleet_port: crate::fleet::DEFAULT_PORT,
            rift_host: "127.0.0.1".into(),
            rift_port: 5000,
            no_register: false,
            serve: false,
            connect: None,
        }
    }
}

impl Options {
    pub fn parse(args: impl IntoIterator<Item = String>) -> Result<Self, String> {
        let mut o = Options::default();
        let mut it = args.into_iter();
        while let Some(a) = it.next() {
            let mut value = |flag: &str| it.next().ok_or_else(|| format!("{flag} requires a value"));
            match a.as_str() {
                "--list" => o.list_joysticks = true,
                "--list-ports" => o.list_ports = true,
                "--no-register" => o.no_register = true,
                "--serve" => o.serve = true,
                "--port" => o.port = Some(value(&a)?),
                "--connect" => o.connect = Some(value(&a)?),
                "--rift-host" => o.rift_host = value(&a)?,
                "--device" => o.device = num(&a, &value(&a)?)?,
                "--baud" => o.baud = num(&a, &value(&a)?)?,
                "--fleet-port" => o.fleet_port = num(&a, &value(&a)?)?,
                "--rift-port" => o.rift_port = num(&a, &value(&a)?)?,
                "--rate" => o.rate = num(&a, &value(&a)?)?,
                "--mode" => {
                    o.mode = Some(match value(&a)?.as_str() {
                        "joystick" => Mode::Joystick,
                        "slider" => Mode::Slider,
                        "ik" => Mode::Ik,
                        "fleet" => Mode::Fleet,
                        other => return Err(format!("Unknown --mode '{other}' (expected joystick, slider, ik or fleet)")),
                    })
                }
                other => return Err(format!("Unknown argument: {other}")),
            }
        }
        if o.connect.is_some() && (o.serve || o.mode == Some(Mode::Fleet)) {
            return Err("--connect can't be combined with --serve or --mode fleet (this controller has no arm of its own)".into());
        }
        Ok(o)
    }
}

fn num<T: std::str::FromStr>(flag: &str, text: &str) -> Result<T, String> {
    text.parse().map_err(|_| format!("{flag} requires a number"))
}
