//! Joystick and gamepad polling through SDL2 - the same library pygame's
//! joystick module wraps - loaded at runtime with libloading, so building needs
//! no native SDL2 files and a missing SDL2 just means "no joystick". Windows: put
//! SDL2.dll next to the exe (or on PATH). Linux: install libsdl2 (e.g. `apt
//! install libsdl2-2.0-0`).
//!
//! A plain joystick (ARM's own stick) is read as-is. A gamepad SDL knows the
//! layout of (Xbox, PlayStation, Switch Pro...) is read through SDL's game
//! controller API and handed out in the stick's numbering: left stick = axes
//! 0/1, right stick across = axis 2 (wrist roll), D-pad = the hat, A/B/X/Y =
//! buttons 0-3. `pick()` takes a joystick first, else a gamepad, like
//! controller.py's pick_joystick().

use libloading::Library;
use std::ffi::{c_char, c_int, c_void, CStr};
use std::sync::OnceLock;

const SDL_INIT_JOYSTICK: u32 = 0x0000_0200;
const SDL_INIT_GAMECONTROLLER: u32 = 0x0000_2000;
const SDL_HAT_UP: u8 = 0x01;
const SDL_HAT_DOWN: u8 = 0x04;
// SDL_GameControllerAxis / SDL_GameControllerButton
const PAD_AXES: [c_int; 3] = [0, 1, 2]; // LEFTX, LEFTY, RIGHTX
const PAD_BUTTONS: [c_int; 4] = [0, 1, 2, 3]; // A, B, X, Y
const PAD_DPAD_UP: c_int = 11;
const PAD_DPAD_DOWN: c_int = 12;

#[cfg(target_os = "windows")]
const LIB_NAMES: &[&str] = &["SDL2.dll"];
#[cfg(target_os = "macos")]
const LIB_NAMES: &[&str] = &["libSDL2-2.0.0.dylib", "libSDL2.dylib"];
#[cfg(all(unix, not(target_os = "macos")))]
const LIB_NAMES: &[&str] = &["libSDL2-2.0.so.0", "libSDL2.so"];

type Js = *mut c_void;
type Pad = *mut c_void;

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
    device_instance_id: unsafe extern "C" fn(c_int) -> i32,
    instance_id: unsafe extern "C" fn(Js) -> i32,
    attached: unsafe extern "C" fn(Js) -> c_int,
    is_game_controller: unsafe extern "C" fn(c_int) -> c_int,
    pad_open: unsafe extern "C" fn(c_int) -> Pad,
    pad_close: unsafe extern "C" fn(Pad),
    pad_joystick: unsafe extern "C" fn(Pad) -> Js,
    pad_name: unsafe extern "C" fn(Pad) -> *const c_char,
    pad_axis: unsafe extern "C" fn(Pad, c_int) -> i16,
    pad_button: unsafe extern "C" fn(Pad, c_int) -> u8,
}

struct Sdl {
    _lib: Library, // keeps the function pointers in `api` valid
    api: Api,
}

fn get<T: Copy>(lib: &Library, name: &str) -> Result<T, String> {
    let symbol = unsafe { lib.get::<T>(format!("{name}\0").as_bytes()) };
    symbol.map(|s| *s).map_err(|e| format!("SDL2 is missing {name}: {e}"))
}

fn load_api() -> Result<Sdl, String> {
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
        if init(SDL_INIT_JOYSTICK | SDL_INIT_GAMECONTROLLER) != 0 {
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
        device_instance_id: get(&lib, "SDL_JoystickGetDeviceInstanceID")?,
        instance_id: get(&lib, "SDL_JoystickInstanceID")?,
        attached: get(&lib, "SDL_JoystickGetAttached")?,
        is_game_controller: get(&lib, "SDL_IsGameController")?,
        pad_open: get(&lib, "SDL_GameControllerOpen")?,
        pad_close: get(&lib, "SDL_GameControllerClose")?,
        pad_joystick: get(&lib, "SDL_GameControllerGetJoystick")?,
        pad_name: get(&lib, "SDL_GameControllerName")?,
        pad_axis: get(&lib, "SDL_GameControllerGetAxis")?,
        pad_button: get(&lib, "SDL_GameControllerGetButton")?,
    };
    Ok(Sdl { _lib: lib, api })
}

/// SDL2, loaded and initialised once for the whole run.
fn sdl() -> Result<&'static Sdl, String> {
    static SDL: OnceLock<Result<Sdl, String>> = OnceLock::new();
    SDL.get_or_init(load_api).as_ref().map_err(|e| e.clone())
}

unsafe fn cstr(p: *const c_char) -> String {
    if p.is_null() {
        "?".into()
    } else {
        CStr::from_ptr(p).to_string_lossy().into_owned()
    }
}

pub struct Joystick {
    api: &'static Api,
    js: Js,
    pad: Pad, // null for a plain joystick
    pub name: String,
    instance_id: i32,
    axes: i32,
    hats: i32,
    buttons: i32,
}

impl Joystick {
    fn open_index(sdl: &'static Sdl, index: i32) -> Result<Self, String> {
        let api = &sdl.api;
        unsafe {
            if (api.is_game_controller)(index) != 0 {
                let pad = (api.pad_open)(index);
                if !pad.is_null() {
                    let js = (api.pad_joystick)(pad);
                    let (name, instance_id) = (cstr((api.pad_name)(pad)), (api.instance_id)(js));
                    return Ok(Self { api, js, pad, name, instance_id, axes: 3, hats: 1, buttons: 4 });
                }
            }
            let js = (api.open)(index);
            if js.is_null() {
                return Err("SDL_JoystickOpen failed".into());
            }
            let name = cstr((api.name_for_index)(index));
            let instance_id = (api.instance_id)(js);
            let (axes, hats, buttons) = ((api.num_axes)(js), (api.num_hats)(js), (api.num_buttons)(js));
            Ok(Self { api, js, pad: std::ptr::null_mut(), name, instance_id, axes, hats, buttons })
        }
    }

    pub fn is_gamepad(&self) -> bool {
        !self.pad.is_null()
    }

    fn attached(&self) -> bool {
        unsafe { (self.api.attached)(self.js) != 0 }
    }

    pub fn update(&self) {
        unsafe { (self.api.update)() }
    }

    /// Axis value in [-1, 1] (0 if the device doesn't have that axis).
    pub fn axis(&self, i: i32) -> f64 {
        if self.axes <= i || i < 0 {
            return 0.0;
        }
        let raw = unsafe {
            if self.is_gamepad() {
                (self.api.pad_axis)(self.pad, PAD_AXES[i as usize])
            } else {
                (self.api.get_axis)(self.js, i)
            }
        };
        raw as f64 / 32768.0
    }

    /// Hat Y component like pygame's get_hat(): +1 up, -1 down, 0 centred.
    pub fn hat_y(&self, i: i32) -> i32 {
        if self.hats <= i {
            return 0;
        }
        let (up, down) = unsafe {
            if self.is_gamepad() {
                ((self.api.pad_button)(self.pad, PAD_DPAD_UP) != 0, (self.api.pad_button)(self.pad, PAD_DPAD_DOWN) != 0)
            } else {
                let h = (self.api.get_hat)(self.js, i);
                (h & SDL_HAT_UP != 0, h & SDL_HAT_DOWN != 0)
            }
        };
        if up {
            1
        } else if down {
            -1
        } else {
            0
        }
    }

    pub fn button(&self, i: i32) -> bool {
        if self.buttons <= i || i < 0 {
            return false;
        }
        unsafe {
            if self.is_gamepad() {
                (self.api.pad_button)(self.pad, PAD_BUTTONS[i as usize]) != 0
            } else {
                (self.api.get_button)(self.js, i) != 0
            }
        }
    }
}

impl Drop for Joystick {
    fn drop(&mut self) {
        unsafe {
            if self.is_gamepad() {
                (self.api.pad_close)(self.pad)
            } else {
                (self.api.close)(self.js)
            }
        }
    }
}

/// The device index to drive with: `device` if given, else the first plain
/// joystick (ARM's own stick comes first), else the first gamepad.
fn pick_index(api: &Api, device: Option<i32>) -> Option<i32> {
    let count = unsafe { (api.num_joysticks)() };
    if let Some(d) = device {
        return (0..count).contains(&d).then_some(d);
    }
    let first_stick = (0..count).find(|&i| unsafe { (api.is_game_controller)(i) } == 0);
    first_stick.or((count > 0).then_some(0))
}

/// Looks at what's plugged in (call it every second or so) and makes `current`
/// the device to use: kept if it's still the right one, else replaced (the old
/// one is closed) or set to None. Returns whether it changed.
pub fn pick(device: Option<i32>, current: &mut Option<Joystick>) -> Result<bool, String> {
    let sdl = sdl()?;
    let api = &sdl.api;
    unsafe { (api.update)() }; // also notices devices plugged in or out
    let index = pick_index(api, device);
    if let (Some(cur), Some(i)) = (current.as_ref(), index) {
        if cur.attached() && unsafe { (api.device_instance_id)(i) } == cur.instance_id {
            return Ok(false);
        }
    }
    let had = current.take().is_some(); // dropping it closes it
    match index {
        Some(i) => {
            *current = Some(Joystick::open_index(sdl, i)?);
            Ok(true)
        }
        None => Ok(had),
    }
}

/// One line per connected device, for --list.
pub fn describe_devices() -> Result<Vec<String>, String> {
    let sdl = sdl()?;
    let count = unsafe { (sdl.api.num_joysticks)() };
    let mut lines = Vec::new();
    for i in 0..count {
        if let Ok(j) = Joystick::open_index(sdl, i) {
            lines.push(format!(
                "  [{i}] {}  ({}, axes={}, buttons={}, hats={})",
                j.name,
                if j.is_gamepad() { "gamepad" } else { "joystick" },
                j.axes,
                j.buttons,
                j.hats
            ));
        }
    }
    Ok(lines)
}
