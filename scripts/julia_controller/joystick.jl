# joystick.jl - The joystick or gamepad to drive with, read through SDL2 like
# controller.py's pygame joystick. A plain joystick (ARM's own stick) is read
# as-is. A gamepad SDL knows the layout of (Xbox, PlayStation, Switch Pro...)
# is read through SDL's game controller API and handed out in the stick's
# numbering: left stick = axes 0/1, right stick across = axis 2 (wrist roll),
# D-pad = the hat, A/B/X/Y = buttons 0-3. pick_input() takes a joystick first,
# else a gamepad, like controller.py's pick_joystick().

struct Input
    js::Ptr{SDL_Joystick}
    pad::Ptr{SDL_GameController}  # C_NULL for a plain joystick
    name::String
end

is_gamepad(inp::Input) = inp.pad != C_NULL
input_kind(inp::Input) = is_gamepad(inp) ? "gamepad" : "joystick"

const PAD_AXES = (SDL_CONTROLLER_AXIS_LEFTX, SDL_CONTROLLER_AXIS_LEFTY, SDL_CONTROLLER_AXIS_RIGHTX)
const PAD_BUTTONS = (SDL_CONTROLLER_BUTTON_A, SDL_CONTROLLER_BUTTON_B, SDL_CONTROLLER_BUTTON_X, SDL_CONTROLLER_BUTTON_Y)

function open_input(index)
    if SDL_IsGameController(index) == SDL_TRUE
        pad = SDL_GameControllerOpen(index)
        pad != C_NULL && return Input(SDL_GameControllerGetJoystick(pad), pad, unsafe_string(SDL_GameControllerName(pad)))
    end
    js = SDL_JoystickOpen(index)
    js == C_NULL && return nothing
    return Input(js, C_NULL, unsafe_string(SDL_JoystickName(js)))
end

function close_input(inp::Input)
    is_gamepad(inp) ? SDL_GameControllerClose(inp.pad) : SDL_JoystickClose(inp.js)
end

# The device index to drive with: `device` if given (>= 0), else the first
# plain joystick (ARM's own stick comes first), else the first gamepad.
function pick_index(device)
    count = SDL_NumJoysticks()
    device >= 0 && return device < count ? device : nothing
    for i in 0:count-1
        SDL_IsGameController(i) == SDL_TRUE || return i
    end
    return count > 0 ? 0 : nothing
end

# The device to use now: `current` if it's still the right one, else a newly
# opened one (current is closed) or nothing. Call it when one is plugged in / out.
function pick_input(device, current)
    index = pick_index(device)
    if current !== nothing && index !== nothing && SDL_JoystickGetAttached(current.js) == SDL_TRUE &&
       SDL_JoystickGetDeviceInstanceID(index) == SDL_JoystickInstanceID(current.js)
        return current
    end
    current !== nothing && close_input(current)
    return index === nothing ? nothing : open_input(index)
end

# Axis value in [-1, 1] (0 if the device doesn't have that axis).
function input_axis(inp::Input, i)
    if is_gamepad(inp)
        return i < length(PAD_AXES) ? SDL_GameControllerGetAxis(inp.pad, PAD_AXES[i + 1]) / 32768.0 : 0.0
    end
    return SDL_JoystickNumAxes(inp.js) > i ? SDL_JoystickGetAxis(inp.js, i) / 32768.0 : 0.0
end

# The hat's Y component like pygame's get_hat(): +1 up, -1 down, 0 centred.
function input_hat_y(inp::Input, i)
    if is_gamepad(inp)
        SDL_GameControllerGetButton(inp.pad, SDL_CONTROLLER_BUTTON_DPAD_UP) != 0 && return 1
        SDL_GameControllerGetButton(inp.pad, SDL_CONTROLLER_BUTTON_DPAD_DOWN) != 0 && return -1
        return 0
    end
    SDL_JoystickNumHats(inp.js) > i || return 0
    hat = SDL_JoystickGetHat(inp.js, i)
    return (hat & SDL_HAT_UP) != 0 ? 1 : ((hat & SDL_HAT_DOWN) != 0 ? -1 : 0)
end

function input_button(inp::Input, i)
    if is_gamepad(inp)
        return i < length(PAD_BUTTONS) && SDL_GameControllerGetButton(inp.pad, PAD_BUTTONS[i + 1]) != 0
    end
    return SDL_JoystickNumButtons(inp.js) > i && SDL_JoystickGetButton(inp.js, i) != 0
end
