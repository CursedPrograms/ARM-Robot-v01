package main

// Joystick polling through SDL2 - the same library pygame's joystick module
// wraps - loaded at runtime with purego (no cgo, no SDL headers needed), so a
// missing SDL2 just means "no joystick". Windows: put SDL2.dll next to the exe
// (or on PATH). Linux: install libsdl2 (e.g. `apt install libsdl2-2.0-0`).

import (
	"fmt"
	"runtime"
	"unsafe"

	"github.com/ebitengine/purego"
)

const (
	sdlInitJoystick = 0x00000200
	sdlHatUp        = 0x01
	sdlHatDown      = 0x04
)

var (
	sdlLoaded bool
	sdlErr    error

	sdlInit                 func(uint32) int32
	sdlSetHint              func(string, string) int32
	sdlGetError             func() uintptr
	sdlNumJoysticks         func() int32
	sdlJoystickNameForIndex func(int32) uintptr
	sdlJoystickOpen         func(int32) uintptr
	sdlJoystickClose        func(uintptr)
	sdlJoystickNumAxes      func(uintptr) int32
	sdlJoystickNumHats      func(uintptr) int32
	sdlJoystickNumButtons   func(uintptr) int32
	sdlJoystickUpdate       func()
	sdlJoystickGetAxis      func(uintptr, int32) int16
	sdlJoystickGetHat       func(uintptr, int32) uint8
	sdlJoystickGetButton    func(uintptr, int32) uint8
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
	if sdlErr != nil {
		return sdlErr
	}

	// Without this, DirectInput on Windows only reports input while an SDL window has focus - and we have none.
	sdlSetHint("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
	if sdlInit(sdlInitJoystick) != 0 {
		sdlErr = fmt.Errorf("SDL_Init failed: %s", cString(sdlGetError()))
		return sdlErr
	}
	sdlLoaded = true
	return nil
}

type Joystick struct {
	handle              uintptr
	Name                string
	axes, hats, buttons int32
}

func OpenJoystick(index int) (*Joystick, error) {
	if err := loadSDL(); err != nil {
		return nil, err
	}
	if index < 0 || int32(index) >= sdlNumJoysticks() {
		return nil, fmt.Errorf("no joystick device at that index")
	}
	h := sdlJoystickOpen(int32(index))
	if h == 0 {
		return nil, fmt.Errorf("SDL_JoystickOpen failed: %s", cString(sdlGetError()))
	}
	return &Joystick{
		handle:  h,
		Name:    cString(sdlJoystickNameForIndex(int32(index))),
		axes:    sdlJoystickNumAxes(h),
		hats:    sdlJoystickNumHats(h),
		buttons: sdlJoystickNumButtons(h),
	}, nil
}

func (j *Joystick) Update() { sdlJoystickUpdate() }

// Axis returns a value in [-1, 1] (0 if the device doesn't have that axis).
func (j *Joystick) Axis(i int) float64 {
	if int32(i) >= j.axes {
		return 0
	}
	return float64(sdlJoystickGetAxis(j.handle, int32(i))) / 32768.0
}

// HatY is the hat's Y component like pygame's get_hat(): +1 up, -1 down, 0 centred.
func (j *Joystick) HatY(i int) int {
	if int32(i) >= j.hats {
		return 0
	}
	h := sdlJoystickGetHat(j.handle, int32(i))
	switch {
	case h&sdlHatUp != 0:
		return 1
	case h&sdlHatDown != 0:
		return -1
	}
	return 0
}

func (j *Joystick) Button(i int) bool {
	return int32(i) < j.buttons && sdlJoystickGetButton(j.handle, int32(i)) != 0
}

func (j *Joystick) Close() { sdlJoystickClose(j.handle) }

// describeJoysticks returns one line per connected device, for --list.
func describeJoysticks() ([]string, error) {
	if err := loadSDL(); err != nil {
		return nil, err
	}
	var lines []string
	for i := int32(0); i < sdlNumJoysticks(); i++ {
		h := sdlJoystickOpen(i)
		if h == 0 {
			continue
		}
		lines = append(lines, fmt.Sprintf("  [%d] %s  (axes=%d, buttons=%d, hats=%d)",
			i, cString(sdlJoystickNameForIndex(i)), sdlJoystickNumAxes(h), sdlJoystickNumButtons(h), sdlJoystickNumHats(h)))
		sdlJoystickClose(h)
	}
	return lines, nil
}
