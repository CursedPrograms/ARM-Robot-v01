//! Joystick polling through SDL2 - the same library pygame's joystick module
//! wraps - loaded at runtime with libloading, so building needs no native SDL2
//! files and a missing SDL2 just means "no joystick". Windows: put SDL2.dll next
//! to the exe (or on PATH). Linux: install libsdl2 (e.g. `apt install libsdl2-2.0-0`).

use libloading::Library;
use std::ffi::{c_char, c_int, c_void, CStr};

const SDL_INIT_JOYSTICK: u32 = 0x0000_0200;
const SDL_HAT_UP: u8 = 0x01;
const SDL_HAT_DOWN: u8 = 0x04;

#[cfg(target_os = "windows")]
const LIB_NAMES: &[&str] = &["SDL2.dll"];
#[cfg(target_os = "macos")]
const LIB_NAMES: &[&str] = &["libSDL2-2.0.0.dylib", "libSDL2.dylib"];
#[cfg(all(unix, not(target_os = "macos")))]
const LIB_NAMES: &[&str] = &["libSDL2-2.0.so.0", "libSDL2.so"];

type Js = *mut c_void;

struct Api {
    num_joysticks: unsafe extern "C" fn() -> c_int,
    name_for_index: unsafe extern "C" fn(c_int) -> *const c_char,
    open: unsafe extern "C" fn(c_int) -> Js,
    close: unsafe extern "C" fn(Js),
    num_axes: unsafe extern "C" fn(Js) -> c_int,
    num_hats: unsafe extern "C" fn(Js) -> c_int,
    num_buttons: unsafe extern "C" fn(Js) -> c_int,
    update: unsafe extern "C" fn(),
    get_axis: unsafe extern "C" fn(Js, c_int) -> i16,
    get_hat: unsafe extern "C" fn(Js, c_int) -> u8,
    get_button: unsafe extern "C" fn(Js, c_int) -> u8,
}

fn get<T: Copy>(lib: &Library, name: &str) -> Result<T, String> {
    let symbol = unsafe { lib.get::<T>(format!("{name}\0").as_bytes()) };
    symbol.map(|s| *s).map_err(|e| format!("SDL2 is missing {name}: {e}"))
}

fn load_api() -> Result<(Library, Api), String> {
    let mut last_err = String::from("no SDL2 library name for this OS");
    let mut loaded = None;
    for name in LIB_NAMES {
        match unsafe { Library::new(name) } {
            Ok(l) => {
                loaded = Some(l);
                break;
            }
            Err(e) => last_err = e.to_string(),
        }
    }
    let lib = loaded.ok_or_else(|| format!("could not load SDL2 ({last_err})"))?;

    let init: unsafe extern "C" fn(u32) -> c_int = get(&lib, "SDL_Init")?;
    let set_hint: unsafe extern "C" fn(*const c_char, *const c_char) -> c_int = get(&lib, "SDL_SetHint")?;
    let get_error: unsafe extern "C" fn() -> *const c_char = get(&lib, "SDL_GetError")?;
    unsafe {
        // Without this, DirectInput on Windows only reports input while an SDL window has focus - and we have none.
        set_hint(c"SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS".as_ptr(), c"1".as_ptr());
        if init(SDL_INIT_JOYSTICK) != 0 {
            return Err(cstr(get_error()));
        }
    }

    let api = Api {
        num_joysticks: get(&lib, "SDL_NumJoysticks")?,
        name_for_index: get(&lib, "SDL_JoystickNameForIndex")?,
        open: get(&lib, "SDL_JoystickOpen")?,
        close: get(&lib, "SDL_JoystickClose")?,
        num_axes: get(&lib, "SDL_JoystickNumAxes")?,
        num_hats: get(&lib, "SDL_JoystickNumHats")?,
        num_buttons: get(&lib, "SDL_JoystickNumButtons")?,
        update: get(&lib, "SDL_JoystickUpdate")?,
        get_axis: get(&lib, "SDL_JoystickGetAxis")?,
        get_hat: get(&lib, "SDL_JoystickGetHat")?,
        get_button: get(&lib, "SDL_JoystickGetButton")?,
    };
    Ok((lib, api))
}

unsafe fn cstr(p: *const c_char) -> String {
    if p.is_null() {
        "?".into()
    } else {
        CStr::from_ptr(p).to_string_lossy().into_owned()
    }
}

pub struct Joystick {
    _lib: Library, // keeps the function pointers in `api` valid
    api: Api,
    js: Js,
    pub name: String,
    axes: i32,
    hats: i32,
    buttons: i32,
}

impl Joystick {
    pub fn open(index: i32) -> Result<Self, String> {
        let (lib, api) = load_api()?;
        let count = unsafe { (api.num_joysticks)() };
        if index < 0 || index >= count {
            return Err("no joystick device at that index".into());
        }
        let js = unsafe { (api.open)(index) };
        if js.is_null() {
            return Err("SDL_JoystickOpen failed".into());
        }
        let name = unsafe { cstr((api.name_for_index)(index)) };
        let (axes, hats, buttons) = unsafe { ((api.num_axes)(js), (api.num_hats)(js), (api.num_buttons)(js)) };
        Ok(Self { _lib: lib, api, js, name, axes, hats, buttons })
    }

    pub fn update(&self) {
        unsafe { (self.api.update)() }
    }

    /// Axis value in [-1, 1] (0 if the device doesn't have that axis).
    pub fn axis(&self, i: i32) -> f64 {
        if self.axes > i {
            unsafe { (self.api.get_axis)(self.js, i) as f64 / 32768.0 }
        } else {
            0.0
        }
    }

    /// Hat Y component like pygame's get_hat(): +1 up, -1 down, 0 centred.
    pub fn hat_y(&self, i: i32) -> i32 {
        if self.hats <= i {
            return 0;
        }
        let h = unsafe { (self.api.get_hat)(self.js, i) };
        if h & SDL_HAT_UP != 0 {
            1
        } else if h & SDL_HAT_DOWN != 0 {
            -1
        } else {
            0
        }
    }

    pub fn button(&self, i: i32) -> bool {
        self.buttons > i && unsafe { (self.api.get_button)(self.js, i) != 0 }
    }
}

impl Drop for Joystick {
    fn drop(&mut self) {
        unsafe { (self.api.close)(self.js) }
    }
}

/// One line per connected device, for --list.
pub fn describe_devices() -> Result<Vec<String>, String> {
    let (_lib, api) = load_api()?;
    let mut lines = Vec::new();
    unsafe {
        for i in 0..(api.num_joysticks)() {
            let js = (api.open)(i);
            if js.is_null() {
                continue;
            }
            lines.push(format!(
                "  [{i}] {}  (axes={}, buttons={}, hats={})",
                cstr((api.name_for_index)(i)),
                (api.num_axes)(js),
                (api.num_buttons)(js),
                (api.num_hats)(js)
            ));
            (api.close)(js);
        }
    }
    Ok(lines)
}
