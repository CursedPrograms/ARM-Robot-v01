package main

// Joystick and gamepad polling through SDL2 - the same library pygame's
// joystick module wraps - loaded at runtime with purego (no cgo, no SDL headers
// needed), so a missing SDL2 just means "no joystick". Windows: put SDL2.dll
// next to the exe (or on PATH). Linux: install libsdl2 (e.g. `apt install
// libsdl2-2.0-0`).
//
// A plain joystick (ARM's own stick) is read as-is. A gamepad SDL knows the
// layout of (Xbox, PlayStation, Switch Pro...) is read through SDL's game
// controller API and handed out in the stick's numbering: left stick = axes
// 0/1, right stick across = axis 2 (wrist roll), D-pad = the hat, A/B/X/Y =
// buttons 0-3. PickJoystick takes a joystick first, else a gamepad, like
// controller.py's pick_joystick().

import (
	"fmt"
	"runtime"
	"unsafe"

	"github.com/ebitengine/purego"
)

const (
	sdlInitJoystick       = 0x00000200
	sdlInitGameController = 0x00002000
	sdlHatUp              = 0x01
	sdlHatDown            = 0x04
	sdlPadDpadUp          = 11 // SDL_CONTROLLER_BUTTON_DPAD_UP
	sdlPadDpadDown        = 12
)

// SDL_GameControllerAxis LEFTX, LEFTY, RIGHTX and SDL_GameControllerButton A, B, X, Y,
// in the stick's numbering.
var (
	padAxes    = []int32{0, 1, 2}
	padButtons = []int32{0, 1, 2, 3}
)

var (
	sdlLoaded bool
	sdlErr    error

	sdlInit                        func(uint32) int32
	sdlSetHint                     func(string, string) int32
	sdlGetError                    func() uintptr
	sdlNumJoysticks                func() int32
	sdlJoystickNameForIndex        func(int32) uintptr
	sdlJoystickOpen                func(int32) uintptr
	sdlJoystickClose               func(uintptr)
	sdlJoystickNumAxes             func(uintptr) int32
	sdlJoystickNumHats             func(uintptr) int32
	sdlJoystickNumButtons          func(uintptr) int32
	sdlJoystickUpdate              func()
	sdlJoystickGetAxis             func(uintptr, int32) int16
	sdlJoystickGetHat              func(uintptr, int32) uint8
	sdlJoystickGetButton           func(uintptr, int32) uint8
	sdlJoystickGetDeviceInstanceID func(int32) int32
	sdlJoystickInstanceID          func(uintptr) int32
	sdlJoystickGetAttached         func(uintptr) int32
	sdlIsGameController            func(int32) int32
	sdlGameControllerOpen          func(int32) uintptr
	sdlGameControllerClose         func(uintptr)
	sdlGameControllerGetJoystick   func(uintptr) uintptr
	sdlGameControllerName          func(uintptr) uintptr
	sdlGameControllerGetAxis       func(uintptr, int32) int16
	sdlGameControllerGetButton     func(uintptr, int32) uint8
)

func sdlLibraryNames() []string {
	switch runtime.GOOS {
	case "windows":
		return []string{"SDL2.dll"}
	case "darwin":
		return []string{"libSDL2-2.0.0.dylib", "libSDL2.dylib"}
	default:
		return []string{"libSDL2-2.0.so.0", "libSDL2.so"}
	}
}

// cString reads a NUL-terminated C string that SDL owns.
func cString(p uintptr) string {
	if p == 0 {
		return "?"
	}
	var b []byte
	for {
		c := *(*byte)(unsafe.Pointer(p))
		if c == 0 {
			return string(b)
		}
		b = append(b, c)
		p++
	}
}

func loadSDL() (result error) {
	if sdlLoaded || sdlErr != nil {
		return sdlErr
	}
	var lib uintptr
	var err error
	for _, name := range sdlLibraryNames() {
		if lib, err = openLibrary(name); err == nil {
			break
		}
	}
	if err != nil {
		sdlErr = fmt.Errorf("could not load SDL2 (%v)", err)
		return sdlErr
	}

	// purego panics if a symbol is missing; turn that into an error.
	defer func() {
		if r := recover(); r != nil {
			sdlErr = fmt.Errorf("SDL2 is missing a function: %v", r)
			result = sdlErr
		}
	}()
	purego.RegisterLibFunc(&sdlInit, lib, "SDL_Init")
	purego.RegisterLibFunc(&sdlSetHint, lib, "SDL_SetHint")
	purego.RegisterLibFunc(&sdlGetError, lib, "SDL_GetError")
	purego.RegisterLibFunc(&sdlNumJoysticks, lib, "SDL_NumJoysticks")
	purego.RegisterLibFunc(&sdlJoystickNameForIndex, lib, "SDL_JoystickNameForIndex")
	purego.RegisterLibFunc(&sdlJoystickOpen, lib, "SDL_JoystickOpen")
	purego.RegisterLibFunc(&sdlJoystickClose, lib, "SDL_JoystickClose")
	purego.RegisterLibFunc(&sdlJoystickNumAxes, lib, "SDL_JoystickNumAxes")
	purego.RegisterLibFunc(&sdlJoystickNumHats, lib, "SDL_JoystickNumHats")
	purego.RegisterLibFunc(&sdlJoystickNumButtons, lib, "SDL_JoystickNumButtons")
	purego.RegisterLibFunc(&sdlJoystickUpdate, lib, "SDL_JoystickUpdate")
	purego.RegisterLibFunc(&sdlJoystickGetAxis, lib, "SDL_JoystickGetAxis")
	purego.RegisterLibFunc(&sdlJoystickGetHat, lib, "SDL_JoystickGetHat")
	purego.RegisterLibFunc(&sdlJoystickGetButton, lib, "SDL_JoystickGetButton")
	purego.RegisterLibFunc(&sdlJoystickGetDeviceInstanceID, lib, "SDL_JoystickGetDeviceInstanceID")
	purego.RegisterLibFunc(&sdlJoystickInstanceID, lib, "SDL_JoystickInstanceID")
	purego.RegisterLibFunc(&sdlJoystickGetAttached, lib, "SDL_JoystickGetAttached")
	purego.RegisterLibFunc(&sdlIsGameController, lib, "SDL_IsGameController")
	purego.RegisterLibFunc(&sdlGameControllerOpen, lib, "SDL_GameControllerOpen")
	purego.RegisterLibFunc(&sdlGameControllerClose, lib, "SDL_GameControllerClose")
	purego.RegisterLibFunc(&sdlGameControllerGetJoystick, lib, "SDL_GameControllerGetJoystick")
	purego.RegisterLibFunc(&sdlGameControllerName, lib, "SDL_GameControllerName")
	purego.RegisterLibFunc(&sdlGameControllerGetAxis, lib, "SDL_GameControllerGetAxis")
	purego.RegisterLibFunc(&sdlGameControllerGetButton, lib, "SDL_GameControllerGetButton")
	if sdlErr != nil {
		return sdlErr
	}

	// Without this, DirectInput on Windows only reports input while an SDL window has focus - and we have none.
	sdlSetHint("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
	if sdlInit(sdlInitJoystick|sdlInitGameController) != 0 {
		sdlErr = fmt.Errorf("SDL_Init failed: %s", cString(sdlGetError()))
		return sdlErr
	}
	sdlLoaded = true
	return nil
}

type Joystick struct {
	handle              uintptr
	pad                 uintptr // 0 for a plain joystick
	instanceID          int32
	Name                string
	axes, hats, buttons int32
}

func openJoystickIndex(index int32) (*Joystick, error) {
	if sdlIsGameController(index) != 0 {
		if pad := sdlGameControllerOpen(index); pad != 0 {
			h := sdlGameControllerGetJoystick(pad)
			return &Joystick{handle: h, pad: pad, instanceID: sdlJoystickInstanceID(h),
				Name: cString(sdlGameControllerName(pad)), axes: 3, hats: 1, buttons: 4}, nil
		}
	}
	h := sdlJoystickOpen(index)
	if h == 0 {
		return nil, fmt.Errorf("SDL_JoystickOpen failed: %s", cString(sdlGetError()))
	}
	return &Joystick{
		handle:     h,
		instanceID: sdlJoystickInstanceID(h),
		Name:       cString(sdlJoystickNameForIndex(index)),
		axes:       sdlJoystickNumAxes(h),
		hats:       sdlJoystickNumHats(h),
		buttons:    sdlJoystickNumButtons(h),
	}, nil
}

// pickIndex is the device index to drive with: device if given (>= 0), else
// the first plain joystick (ARM's own stick comes first), else the first
// gamepad. -1 if nothing is plugged in.
func pickIndex(device int) int32 {
	count := sdlNumJoysticks()
	if device >= 0 {
		if int32(device) < count {
			return int32(device)
		}
		return -1
	}
	for i := int32(0); i < count; i++ {
		if sdlIsGameController(i) == 0 {
			return i
		}
	}
	if count > 0 {
		return 0
	}
	return -1
}

// PickJoystick looks at what's plugged in (call it every second or so) and
// returns the device to use: current if it's still the right one, else a newly
// opened one (current is closed) or nil. changed says whether it's a different one.
func PickJoystick(device int, current *Joystick) (j *Joystick, changed bool, err error) {
	if err := loadSDL(); err != nil {
		return nil, current != nil, err
	}
	sdlJoystickUpdate() // also notices devices plugged in or out
	index := pickIndex(device)
	if current != nil && index >= 0 && sdlJoystickGetAttached(current.handle) != 0 &&
		sdlJoystickGetDeviceInstanceID(index) == current.instanceID {
		return current, false, nil
	}
	if current != nil {
		current.Close()
	}
	if index < 0 {
		return nil, current != nil, nil
	}
	j, err = openJoystickIndex(index)
	return j, true, err
}

func (j *Joystick) IsGamepad() bool { return j.pad != 0 }

func (j *Joystick) Update() { sdlJoystickUpdate() }

// Axis returns a value in [-1, 1] (0 if the device doesn't have that axis).
func (j *Joystick) Axis(i int) float64 {
	if i < 0 || int32(i) >= j.axes {
		return 0
	}
	if j.IsGamepad() {
		return float64(sdlGameControllerGetAxis(j.pad, padAxes[i])) / 32768.0
	}
	return float64(sdlJoystickGetAxis(j.handle, int32(i))) / 32768.0
}

// HatY is the hat's Y component like pygame's get_hat(): +1 up, -1 down, 0 centred.
func (j *Joystick) HatY(i int) int {
	if int32(i) >= j.hats {
		return 0
	}
	var up, down bool
	if j.IsGamepad() {
		up, down = sdlGameControllerGetButton(j.pad, sdlPadDpadUp) != 0, sdlGameControllerGetButton(j.pad, sdlPadDpadDown) != 0
	} else {
		h := sdlJoystickGetHat(j.handle, int32(i))
		up, down = h&sdlHatUp != 0, h&sdlHatDown != 0
	}
	switch {
	case up:
		return 1
	case down:
		return -1
	}
	return 0
}

func (j *Joystick) Button(i int) bool {
	if i < 0 || int32(i) >= j.buttons {
		return false
	}
	if j.IsGamepad() {
		return sdlGameControllerGetButton(j.pad, padButtons[i]) != 0
	}
	return sdlJoystickGetButton(j.handle, int32(i)) != 0
}

func (j *Joystick) Close() {
	if j.IsGamepad() {
		sdlGameControllerClose(j.pad)
	} else {
		sdlJoystickClose(j.handle)
	}
}

// describeJoysticks returns one line per connected device, for --list.
func describeJoysticks() ([]string, error) {
	if err := loadSDL(); err != nil {
		return nil, err
	}
	var lines []string
	for i := int32(0); i < sdlNumJoysticks(); i++ {
		j, err := openJoystickIndex(i)
		if err != nil {
			continue
		}
		kind := "joystick"
		if j.IsGamepad() {
			kind = "gamepad"
		}
		lines = append(lines, fmt.Sprintf("  [%d] %s  (%s, axes=%d, buttons=%d, hats=%d)", i, j.Name, kind, j.axes, j.buttons, j.hats))
		j.Close()
	}
	return lines, nil
}
