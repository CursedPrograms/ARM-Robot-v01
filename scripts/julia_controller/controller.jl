#!/usr/bin/env julia
"""
controller.jl - Julia/SDL2 counterpart of controller.py and the C++
controller (scripts/cpp_controller/): the same four modes
(Joystick/Sliders/IK/Fleet), the same macro record/replay, and the same
wire protocol to scripts/arm/arm.ino and the Fleet HTTP API - reads the
same config.json, records to the same scripts/macros/*.json, and Fleet
mode serves the same scripts/web/ control page, so it's a drop-in
equivalent of the other two controllers.

Modes (click the buttons, or pick one with --mode at startup):
    Joystick - drive motors 1-6 from a joystick (same mapping as controller.py)
    Sliders  - drag on-screen sliders to set each motor's raw angle directly
    IK       - drag X/Y/Z/Pitch/Roll sliders to set a target end-effector pose
    Fleet    - starts an HTTP bridge so the RIFT dashboard (or any browser)
               can see and control this arm over the network

Requires (see Project.toml):
    julia --project=@. -e "import Pkg; Pkg.instantiate()"

Usage:
    julia --project=@. controller.jl --list-ports
    julia --project=@. controller.jl --port COM6
    julia --project=@. controller.jl --port COM6 --mode slider
    julia --project=@. controller.jl --port COM6 --mode fleet --fleet-port 5011
"""

using SimpleDirectMediaLayer.LibSDL2
import LibSerialPort

include(joinpath(@__DIR__, "motor_config.jl"))
include(joinpath(@__DIR__, "kinematics.jl"))
include(joinpath(@__DIR__, "slider.jl"))
include(joinpath(@__DIR__, "macros.jl"))
include(joinpath(@__DIR__, "fleet_server.jl"))
include(joinpath(@__DIR__, "remote_arm.jl"))

const WEB_DIR = normpath(joinpath(@__DIR__, "..", "web"))

# ---- Joystick wiring (Joystick mode only, mirrors controller.py) ----
const AXIS_MOTOR1 = 0
const AXIS_MOTOR2 = 1
const AXIS_MOTOR5 = 2  # A2 and A3 move together on this stick; only A2 is read
const HAT_MOTOR3 = 0
const BUTTON_MOTOR4_BACKWARD = 2
const BUTTON_MOTOR4_FORWARD = 3
const BUTTON_MOTOR6_CLOSE = 0
const DEADZONE = 0.05

# Descriptions that identify likely Arduino USB-serial adapters, for --port auto-detect
const ARDUINO_HINTS = ("arduino", "ch340", "usb-serial", "usb serial", "cp210", "ftdi")

# ---- Window layout ----
const WINDOW_WIDTH, WINDOW_HEIGHT = 560, 700
const MODE_BUTTON_Y = 56
const TRANSPORT_BUTTON_Y = 100
const MACRO_LIST_Y = 138
const MACRO_ROW_H = 16
const MACRO_LIST_MAX = 6
const MARGIN_TOP = 250
const ROW_HEIGHT = 60

# Colours come from colour_scheme.xml at the repo root; these are the fallbacks
# for any role missing from it (or if the file can't be read).
const SCHEME_PATH = joinpath(@__DIR__, "..", "..", "colour_scheme.xml")

function load_scheme()
    scheme = Dict{String,NTuple{3,Int}}(
        "background" => (0x33, 0x29, 0x2F),
        "panel" => (0x33, 0x1F, 0x2B),
        "border" => (0x36, 0x15, 0x29),
        "text" => (0xFF, 0xFF, 0xFF),
        "text_dim" => (0xC9, 0xB6, 0xC1),
        "button" => (0x36, 0x15, 0x29),
        "button_hover" => (0x69, 0x15, 0x48),
        "button_active" => (0x9C, 0x00, 0x60),
        "button_disabled" => (0x33, 0x1F, 0x2B),
        "accent" => (0x9C, 0x00, 0x60),
        "accent_hover" => (0xC2, 0x1F, 0x82),
        "track" => (0x69, 0x15, 0x48),
        "selected" => (0x69, 0x15, 0x48),
        "danger" => (0x96, 0x32, 0x32),
        "danger_hover" => (0xAD, 0x3A, 0x3A),
        "warn" => (0xF0, 0x8C, 0x3C)
    )
    isfile(SCHEME_PATH) || return scheme
    try
        for m in eachmatch(r"<colour\s+name=\"([^\"]+)\"\s+value=\"#([0-9A-Fa-f]{6})\"", read(SCHEME_PATH, String))
            n = parse(Int, m.captures[2]; base=16)
            scheme[m.captures[1]] = (n >> 16, (n >> 8) & 0xFF, n & 0xFF)
        end
    catch e
        @warn "could not read colour_scheme.xml, using default colours" exception=e
    end
    return scheme
end

const SCHEME = load_scheme()

const BG_COLOR = SCHEME["background"]
const TEXT_COLOR = SCHEME["text"]
const DISABLED_TEXT_COLOR = SCHEME["text_dim"]
const STATUS_COLOR = SCHEME["text_dim"]
const WARN_COLOR = SCHEME["warn"]
const BUTTON_COLOR = SCHEME["button"]
const BUTTON_HOVER_COLOR = SCHEME["button_hover"]
const BUTTON_ACTIVE_COLOR = SCHEME["button_active"]
const BUTTON_RECORD_COLOR = SCHEME["danger"]
const MACRO_SELECTED_COLOR = SCHEME["selected"]
const TRACK_COLOR = SCHEME["track"]
const KNOB_COLOR = SCHEME["accent"]

# =========================================================================
# Small helpers
# =========================================================================

function axis_to_angle(value, lo, hi; deadzone=DEADZONE)
    abs(value) < deadzone && (value = 0.0)
    angle = (value + 1.0) / 2.0 * (hi - lo) + lo
    return round(Int, angle)
end

point_in(px, py, rect) = rect[1] <= px <= rect[1] + rect[3] && rect[2] <= py <= rect[2] + rect[4]

function list_serial_ports_info()
    # LibSerialPort.list_ports() only prints (it returns nothing), so read libserialport's
    # port list directly to get (name, description) pairs.
    rows = Tuple{String,String}[]
    ports = LibSerialPort.sp_list_ports()
    try
        for port in unsafe_wrap(Array, ports, 64; own=false)
            port == C_NULL && break
            push!(rows, (LibSerialPort.sp_get_port_name(port), LibSerialPort.sp_get_port_description(port)))
        end
    finally
        LibSerialPort.sp_free_port_list(ports)
    end
    return rows
end

function print_serial_ports()
    rows = list_serial_ports_info()
    if isempty(rows)
        println("No serial ports found.")
    else
        println("Available serial ports:")
        for (name, desc) in rows
            println("  $name  -  $desc")
        end
    end
end

# True if the board on `name` answers "WHO" with "I am Arm" (arm.ino), so
# DREAM's board on the same PC isn't picked by mistake.
function answers_i_am_arm(name)
    try
        LibSerialPort.open(name, 115200) do sp
            sleep(2.0)  # board resets when the port opens
            LibSerialPort.sp_flush(sp, LibSerialPort.SP_BUF_INPUT)
            write(sp, "WHO\n")
            deadline = time() + 1.5
            seen = ""
            while time() < deadline
                seen *= String(LibSerialPort.nonblocking_read(sp))
                occursin("i am arm", lowercase(seen)) && return true
                sleep(0.02)
            end
            return false
        end
    catch
        return false  # busy or unusable
    end
end

# Prefers the port that answers "I am Arm"; otherwise the first likely Arduino adapter.
function autodetect_port()
    candidates = [name for (name, desc) in list_serial_ports_info()
                  if any(h -> occursin(h, lowercase(desc)), ARDUINO_HINTS)]
    for name in candidates
        answers_i_am_arm(name) && return name
    end
    return isempty(candidates) ? nothing : first(candidates)
end

function list_joysticks()
    SDL_Init(SDL_INIT_JOYSTICK) == 0 || return println("Could not init joystick subsystem: $(unsafe_string(SDL_GetError()))")
    n = SDL_NumJoysticks()
    if n == 0
        println("No joystick/controller devices found.")
    else
        println("Found $n device(s):")
        for i in 0:(n - 1)
            js = SDL_JoystickOpen(i)
            if js != C_NULL
                name = unsafe_string(SDL_JoystickName(js))
                println("  [$i] $name  (axes=$(SDL_JoystickNumAxes(js)), buttons=$(SDL_JoystickNumButtons(js)), hats=$(SDL_JoystickNumHats(js)))")
                SDL_JoystickClose(js)
            end
        end
    end
    SDL_Quit()
end

function find_system_font()
    candidates = String[]
    if Sys.iswindows()
        fonts = joinpath(get(ENV, "WINDIR", "C:\\Windows"), "Fonts")
        append!(candidates, joinpath.(fonts, ("segoeui.ttf", "arial.ttf", "calibri.ttf", "tahoma.ttf")))
    elseif Sys.isapple()
        append!(candidates, ["/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc"])
    else
        append!(candidates, [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/TTF/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/liberation/LiberationSans-Regular.ttf", "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            "/usr/share/fonts/noto/NotoSans-Regular.ttf",
        ])
    end
    for path in candidates
        isfile(path) && return path
    end
    return nothing
end

function joystick_commands(js, motors)
    SDL_JoystickUpdate()
    numaxes = SDL_JoystickNumAxes(js)
    numhats = SDL_JoystickNumHats(js)
    numbuttons = SDL_JoystickNumButtons(js)

    motor1_val = numaxes > AXIS_MOTOR1 ? SDL_JoystickGetAxis(js, AXIS_MOTOR1) / 32768.0 : 0.0
    motor2_val = numaxes > AXIS_MOTOR2 ? SDL_JoystickGetAxis(js, AXIS_MOTOR2) / 32768.0 : 0.0
    motor5_val = numaxes > AXIS_MOTOR5 ? SDL_JoystickGetAxis(js, AXIS_MOTOR5) / 32768.0 : 0.0

    motor3_val = 0.0
    if numhats > HAT_MOTOR3
        hat = SDL_JoystickGetHat(js, HAT_MOTOR3)
        motor3_val = (hat & SDL_HAT_UP) != 0 ? 1.0 : ((hat & SDL_HAT_DOWN) != 0 ? -1.0 : 0.0)
    end

    motor4_forward = numbuttons > BUTTON_MOTOR4_FORWARD && SDL_JoystickGetButton(js, BUTTON_MOTOR4_FORWARD) != 0
    motor4_backward = numbuttons > BUTTON_MOTOR4_BACKWARD && SDL_JoystickGetButton(js, BUTTON_MOTOR4_BACKWARD) != 0
    motor4_val = motor4_forward && !motor4_backward ? 1.0 : (motor4_backward && !motor4_forward ? -1.0 : 0.0)

    motor6_close = numbuttons > BUTTON_MOTOR6_CLOSE && SDL_JoystickGetButton(js, BUTTON_MOTOR6_CLOSE) != 0
    motors[6]["invert"] && (motor6_close = !motor6_close)
    motor6_angle = motor6_close ? motors[6]["max"] : motors[6]["min"]

    motors[1]["invert"] && (motor1_val = -motor1_val)
    motors[2]["invert"] && (motor2_val = -motor2_val)
    motors[3]["invert"] && (motor3_val = -motor3_val)
    motors[4]["invert"] && (motor4_val = -motor4_val)
    motors[5]["invert"] && (motor5_val = -motor5_val)

    return Dict{Int,Int}(
        motors[1]["channel"] => axis_to_angle(motor1_val, motors[1]["min"], motors[1]["max"]),
        motors[2]["channel"] => axis_to_angle(motor2_val, motors[2]["min"], motors[2]["max"]),
        motors[3]["channel"] => axis_to_angle(motor3_val, motors[3]["min"], motors[3]["max"]),
        motors[4]["channel"] => axis_to_angle(motor4_val, motors[4]["min"], motors[4]["max"]),
        motors[5]["channel"] => axis_to_angle(motor5_val, motors[5]["min"], motors[5]["max"]),
        motors[6]["channel"] => motor6_angle,
    )
end

# Shared arm state: fleet_state.angles is the single set of angles every input
# writes to and every output (serial, web page, RIFT, the sliders) reads from.
# An input whose value changed since last frame writes it (last writer wins);
# inputs that didn't change leave what another input wrote alone. All dicts are
# keyed by motor number.
function merge_local!(local_by_motor, prev_local, fleet_state)
    changed = Dict{Int,Int}()
    lock(fleet_state.lock) do
        for (n, a) in local_by_motor
            if get(prev_local, n, nothing) != a
                fleet_state.angles[n] = a
                changed[n] = a
            end
        end
    end
    empty!(prev_local)
    merge!(prev_local, local_by_motor)
    return changed
end

# Slider positions adopt the shared angles (so web-page/other-input changes show up).
function follow_sliders!(sliders, motor_numbers, fleet_state, prev_local)
    lock(fleet_state.lock) do
        for (sl, n) in zip(sliders, motor_numbers)
            sl.angle = fleet_state.angles[n]
            prev_local[n] = sl.angle
        end
    end
end

function send_commands!(sp, commands, last_sent)
    if commands != last_sent
        if sp !== nothing
            line = join(("$ch:$ang" for (ch, ang) in commands), ",")
            write(sp, line * "\n")
        end
        return copy(commands)
    end
    return last_sent
end

# =========================================================================
# Drawing
# =========================================================================

function fill_rect!(renderer, rect, color)
    SDL_SetRenderDrawColor(renderer, color[1], color[2], color[3], 255)
    r = Ref(SDL_Rect(rect[1], rect[2], rect[3], rect[4]))
    SDL_RenderFillRect(renderer, r)
end

function draw_circle_filled!(renderer, cx, cy, radius, color)
    SDL_SetRenderDrawColor(renderer, color[1], color[2], color[3], 255)
    for dy in -radius:radius
        dx = round(Int, sqrt(max(radius^2 - dy^2, 0)))
        r = Ref(SDL_Rect(cx - dx, cy + dy, 2dx + 1, 1))
        SDL_RenderFillRect(renderer, r)
    end
end

function text_size(font, text::AbstractString)
    isempty(text) && return (0, 0)
    w = Ref{Cint}(0)
    h = Ref{Cint}(0)
    TTF_SizeText(font, text, w, h)
    return Int(w[]), Int(h[])
end

function draw_text!(renderer, font, text::AbstractString, x, y, color)
    isempty(text) && return
    col = SDL_Color(color[1], color[2], color[3], 255)
    surf = TTF_RenderText_Blended(font, text, col)
    surf == C_NULL && return
    tex = SDL_CreateTextureFromSurface(renderer, surf)
    w = Ref{Cint}(0)
    h = Ref{Cint}(0)
    SDL_QueryTexture(tex, C_NULL, C_NULL, w, h)
    dst = Ref(SDL_Rect(round(Int, x), round(Int, y), w[], h[]))
    SDL_RenderCopy(renderer, tex, C_NULL, dst)
    SDL_DestroyTexture(tex)
    SDL_FreeSurface(surf)
end

function draw_text_centered!(renderer, font, text, rect, color)
    tw, th = text_size(font, text)
    draw_text!(renderer, font, text, rect[1] + (rect[3] - tw) ÷ 2, rect[2] + (rect[4] - th) ÷ 2, color)
end

function draw_button!(renderer, font, rect, label, mx, my; active=false, color=nothing, enabled=true)
    bg = color !== nothing ? color :
         active ? BUTTON_ACTIVE_COLOR :
         (point_in(mx, my, rect) ? BUTTON_HOVER_COLOR : BUTTON_COLOR)
    fill_rect!(renderer, rect, bg)
    draw_text_centered!(renderer, font, label, rect, enabled ? TEXT_COLOR : DISABLED_TEXT_COLOR)
end

function draw_slider!(renderer, font, s::Slider)
    fill_rect!(renderer, (SLIDER_X, s.y - 3, SLIDER_WIDTH, 6), TRACK_COLOR)
    draw_circle_filled!(renderer, value_to_x(s), s.y, KNOB_RADIUS, KNOB_COLOR)

    channel_part = s.channel !== nothing ? "ch $(s.channel), " : ""
    draw_text!(renderer, font, "$(s.label) ($(channel_part)$(round(Int, s.lo))-$(round(Int, s.hi)))", 20, s.y - 10, TEXT_COLOR)
    draw_text!(renderer, font, string(s.angle), SLIDER_X + SLIDER_WIDTH + 20, s.y - 10, TEXT_COLOR)
end

macro_row_rect(i) = (30, MACRO_LIST_Y + i * MACRO_ROW_H, 500, MACRO_ROW_H)

# =========================================================================
# CLI args
# =========================================================================

function parse_args(argv)
    opts = Dict{Symbol,Any}(
        :device => 0, :port => nothing, :baud => 115200, :rate => 30.0,
        :mode => nothing, :list => false, :list_ports => false,
        :fleet_port => DEFAULT_FLEET_PORT, :rift_host => "127.0.0.1",
        :rift_port => 5000, :no_register => false, :serve => false, :connect => nothing,
    )
    i = 1
    n = length(argv)
    value_flags = ("--device", "--port", "--baud", "--rate", "--mode", "--fleet-port", "--rift-host", "--rift-port", "--connect")
    while i <= n
        a = argv[i]
        needs_value = a in value_flags
        val = ""
        if needs_value
            i == n && error("$a requires a value")
            val = argv[i + 1]
        end
        if a == "--device"
            opts[:device] = parse(Int, val)
        elseif a == "--port"
            opts[:port] = val
        elseif a == "--baud"
            opts[:baud] = parse(Int, val)
        elseif a == "--rate"
            opts[:rate] = parse(Float64, val)
        elseif a == "--mode"
            val in ("joystick", "slider", "ik", "fleet") || error("Unknown --mode '$val'")
            opts[:mode] = val
        elseif a == "--list"
            opts[:list] = true
        elseif a == "--list-ports"
            opts[:list_ports] = true
        elseif a == "--fleet-port"
            opts[:fleet_port] = parse(Int, val)
        elseif a == "--rift-host"
            opts[:rift_host] = val
        elseif a == "--rift-port"
            opts[:rift_port] = parse(Int, val)
        elseif a == "--no-register"
            opts[:no_register] = true
        elseif a == "--serve"
            opts[:serve] = true
        elseif a == "--connect"
            opts[:connect] = val
        else
            error("Unknown argument: $a")
        end
        i += needs_value ? 2 : 1
    end
    opts[:connect] !== nothing && (opts[:serve] || opts[:mode] == "fleet") &&
        error("--connect can't be combined with --serve or --mode fleet (this controller has no arm of its own)")
    return opts
end

# =========================================================================
# Main
# =========================================================================

function main()
    args = parse_args(ARGS)

    if args[:list]
        list_joysticks()
        return
    end
    if args[:list_ports]
        print_serial_ports()
        return
    end

    motors = load_motor_config()
    geometry = load_geometry()

    SDL_Init(SDL_INIT_VIDEO | SDL_INIT_JOYSTICK | SDL_INIT_EVENTS) == 0 ||
        error("SDL_Init failed: $(unsafe_string(SDL_GetError()))")
    TTF_Init() == 0 || error("TTF_Init failed: $(unsafe_string(SDL_GetError()))")

    font_path = find_system_font()
    font_path === nothing && error("No TrueType font found (Windows: %WINDIR%\\Fonts; Linux: install DejaVu or Liberation fonts, e.g. `sudo apt install fonts-dejavu-core`).")
    font = TTF_OpenFont(font_path, 16)
    small_font = TTF_OpenFont(font_path, 13)

    js = C_NULL
    if SDL_NumJoysticks() > args[:device]
        js = SDL_JoystickOpen(args[:device])
        js != C_NULL && println("Using joystick: $(unsafe_string(SDL_JoystickName(js)))")
    end
    joystick_available = js != C_NULL
    joystick_available || println("No joystick found - Joystick mode will be unavailable.")

    port = args[:connect] !== nothing ? nothing : (args[:port] !== nothing ? args[:port] : autodetect_port())
    sp = nothing
    status = args[:connect] !== nothing ? "Remote arm at $(args[:connect]) (no local serial port)." :
             "No Arduino-like serial port found - display-only mode."
    if port !== nothing
        try
            sp = open(port, args[:baud])
            sleep(2)  # give the Arduino time to reset after the serial connection opens
            status = "Connected to $port @ $(args[:baud]) baud."
        catch e
            status = "Could not open $port: $e"
        end
    end
    println(status)

    window = SDL_CreateWindow("Arm Controller (Julia)", SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
                               WINDOW_WIDTH, WINDOW_HEIGHT, SDL_WINDOW_SHOWN)
    window == C_NULL && error("Could not create window: $(unsafe_string(SDL_GetError()))")
    renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_ACCELERATED)
    renderer == C_NULL && error("Could not create renderer: $(unsafe_string(SDL_GetError()))")

    mode = args[:mode] !== nothing ? args[:mode] : (joystick_available ? "joystick" : "slider")

    slider_mode_sliders = Slider[
        Slider("Motor $n", motors[n]["channel"], motors[n]["min"], motors[n]["max"], motors[n]["rest"],
               MARGIN_TOP + (i - 1) * ROW_HEIGHT)
        for (i, n) in enumerate(sort(collect(keys(motors))))
    ]

    reach = geometry["upperArmLength"] + geometry["forearmLength"] + geometry["wristLength"]
    reach = reach > 0 ? reach : 300
    ik_sliders = Dict(
        "x" => Slider("Target X (mm)", nothing, -reach, reach, 0, MARGIN_TOP + 0 * ROW_HEIGHT),
        "y" => Slider("Target Y (mm)", nothing, -reach, reach, 0, MARGIN_TOP + 1 * ROW_HEIGHT),
        "z" => Slider("Target Z (mm)", nothing, 0, reach, geometry["baseHeight"], MARGIN_TOP + 2 * ROW_HEIGHT),
        "pitch" => Slider("Pitch (deg)", nothing, -90, 90, 0, MARGIN_TOP + 3 * ROW_HEIGHT),
        "roll" => Slider("Roll (motor 5)", motors[5]["channel"], motors[5]["min"], motors[5]["max"], motors[5]["rest"],
                          MARGIN_TOP + 4 * ROW_HEIGHT),
    )
    elbow_down = false
    claw_closed = false
    ik_reachable = true
    last_valid_ik_commands = nothing

    fleet_state = FleetState(Dict{Int,Int}(n => motors[n]["rest"] for n in keys(motors)))
    fleet_started = false
    fleet_error = ""
    fleet_lan_ip = local_lan_ip()

    ensure_fleet_started = () -> begin
        if !fleet_started && isempty(fleet_error) && args[:connect] === nothing  # a client has no arm of its own to serve
            err = start_fleet_server(motors, fleet_state, () -> sp !== nothing;
                                      port=args[:fleet_port], register=!args[:no_register],
                                      rift_host=args[:rift_host], rift_port=args[:rift_port], web_dir=WEB_DIR)
            if isempty(err)
                fleet_started = true
            else
                fleet_error = err
            end
        end
    end
    if mode == "fleet" || args[:serve]
        ensure_fleet_started()
        if !isempty(fleet_error)
            println(fleet_error)
        elseif mode != "fleet"
            status *= "  |  Web: http://$fleet_lan_ip:$(args[:fleet_port])"
            println("Web control on http://$fleet_lan_ip:$(args[:fleet_port])")
        end
    end

    motor_numbers = sort(collect(keys(motors)))
    channel_to_motor = Dict{Int,Int}(motors[n]["channel"] => n for n in motor_numbers)
    prev_local = Dict{Int,Int}()
    last_mode = mode

    remote = args[:connect] !== nothing ? start_remote_arm(args[:connect], fleet_state) : nothing
    adopted = remote === nothing  # a client waits for the hub's real angles before its own inputs may write

    mode_rects = Dict(
        "joystick" => (20, MODE_BUTTON_Y, 122, 34),
        "slider" => (152, MODE_BUTTON_Y, 122, 34),
        "ik" => (284, MODE_BUTTON_Y, 122, 34),
        "fleet" => (416, MODE_BUTTON_Y, 122, 34),
    )
    mode_labels = Dict("joystick" => "Joystick", "slider" => "Sliders", "ik" => "IK", "fleet" => "Fleet")
    record_rect = (30, TRANSPORT_BUTTON_Y, 160, 30)
    play_rect = (200, TRANSPORT_BUTTON_Y, 160, 30)
    elbow_rect = (30, MARGIN_TOP + 5 * ROW_HEIGHT, 150, 30)
    claw_rect = (200, MARGIN_TOP + 5 * ROW_HEIGHT, 150, 30)

    macros = list_macros()
    selected_macro_index = isempty(macros) ? nothing : 1

    recording = false
    record_steps = MacroStep[]
    record_start = time()

    playing = false
    play_steps = MacroStep[]
    play_start = time()
    play_index = 1
    play_prev_mode = mode

    last_sent = Dict{Int,Int}()

    running = true
    try
        while running
            event_ref = Ref{SDL_Event}()
            while Bool(SDL_PollEvent(event_ref))
                evt = event_ref[]
                if evt.type == SDL_QUIT
                    running = false
                elseif evt.type == SDL_KEYDOWN
                    sc = evt.key.keysym.scancode
                    if sc == SDL_SCANCODE_ESCAPE
                        running = false
                    elseif !playing && SDL_SCANCODE_1 <= sc <= SDL_SCANCODE_9
                        idx = Int(sc) - Int(SDL_SCANCODE_1) + 1
                        idx <= length(macros) && (selected_macro_index = idx)
                    end
                elseif evt.type == SDL_MOUSEBUTTONDOWN && evt.button.button == SDL_BUTTON_LEFT
                    mx, my = Int(evt.button.x), Int(evt.button.y)
                    if playing
                        if point_in(mx, my, play_rect)
                            playing = false
                            mode = play_prev_mode
                        end
                    else
                        if point_in(mx, my, mode_rects["joystick"]) && joystick_available
                            mode = "joystick"
                        elseif point_in(mx, my, mode_rects["slider"])
                            mode = "slider"
                        elseif point_in(mx, my, mode_rects["ik"])
                            mode = "ik"
                        elseif point_in(mx, my, mode_rects["fleet"])
                            mode = "fleet"
                            ensure_fleet_started()
                        elseif point_in(mx, my, record_rect)
                            if !recording
                                recording = true
                                record_steps = MacroStep[]
                                record_start = time()
                            else
                                recording = false
                                if !isempty(record_steps)
                                    path = save_macro(record_steps)
                                    println("Saved macro: $(basename(path)) ($(length(record_steps)) steps)")
                                    macros = list_macros()
                                    selected_macro_index = 1
                                end
                            end
                        elseif point_in(mx, my, play_rect) && !isempty(macros) && selected_macro_index !== nothing
                            playing = true
                            play_steps = load_macro(macros[selected_macro_index])
                            play_start = time()
                            play_index = 1
                            play_prev_mode = mode
                        elseif mode == "ik" && point_in(mx, my, elbow_rect)
                            elbow_down = !elbow_down
                        elseif mode == "ik" && point_in(mx, my, claw_rect)
                            claw_closed = !claw_closed
                        else
                            for i in 1:min(length(macros), MACRO_LIST_MAX)
                                if point_in(mx, my, macro_row_rect(i - 1))
                                    selected_macro_index = i
                                end
                            end
                        end
                    end

                    if !playing
                        if mode == "slider"
                            for s in slider_mode_sliders
                                slider_mouse_down!(s, mx, my)
                            end
                        elseif mode == "ik"
                            for s in values(ik_sliders)
                                slider_mouse_down!(s, mx, my)
                            end
                        end
                    end
                elseif evt.type == SDL_MOUSEBUTTONUP && evt.button.button == SDL_BUTTON_LEFT
                    if mode == "slider"
                        for s in slider_mode_sliders
                            slider_mouse_up!(s)
                        end
                    elseif mode == "ik"
                        for s in values(ik_sliders)
                            slider_mouse_up!(s)
                        end
                    end
                elseif evt.type == SDL_MOUSEMOTION
                    mx = Int(evt.motion.x)
                    if mode == "slider"
                        for s in slider_mode_sliders
                            slider_mouse_move!(s, mx)
                        end
                    elseif mode == "ik"
                        for s in values(ik_sliders)
                            slider_mouse_move!(s, mx)
                        end
                    end
                end
            end

            mx_ref, my_ref = Ref{Cint}(0), Ref{Cint}(0)
            SDL_GetMouseState(mx_ref, my_ref)
            mx, my = Int(mx_ref[]), Int(my_ref[])

            # ---- compute + send this frame's commands ----
            warn_text = ""
            if playing
                elapsed = time() - play_start
                while play_index <= length(play_steps) && play_steps[play_index].t <= elapsed
                    last_sent = send_commands!(sp, play_steps[play_index].commands, last_sent)
                    changed = Dict{Int,Int}(channel_to_motor[ch] => a for (ch, a) in play_steps[play_index].commands if haskey(channel_to_motor, ch))
                    lock(fleet_state.lock) do
                        merge!(fleet_state.angles, changed)
                    end
                    remote !== nothing && queue_remote!(remote, changed)
                    play_index += 1
                end
                mode == "slider" && follow_sliders!(slider_mode_sliders, motor_numbers, fleet_state, prev_local)
                if play_index > length(play_steps)
                    playing = false
                    mode = play_prev_mode
                end
            else
                if mode != last_mode
                    empty!(prev_local)
                    mode == "slider" && follow_sliders!(slider_mode_sliders, motor_numbers, fleet_state, prev_local)
                    last_mode = mode
                end

                local_commands = nothing  # channel -> angle from this mode's own input, if any
                if mode == "joystick" && joystick_available
                    local_commands = joystick_commands(js, motors)
                elseif mode == "joystick"
                    warn_text = "No joystick connected."
                elseif mode == "slider"
                    local_commands = Dict{Int,Int}(s.channel => s.angle for s in slider_mode_sliders)
                elseif mode == "ik"
                    if !geometry_ready(geometry)
                        warn_text = "Geometry not measured - fill in config.json's \"geometry\" section."
                    else
                        sol = inverse_kinematics(motors, geometry,
                                                  ik_sliders["x"].angle, ik_sliders["y"].angle, ik_sliders["z"].angle;
                                                  pitch_deg=ik_sliders["pitch"].angle, elbow_down=elbow_down)
                        if sol !== nothing
                            ik_reachable = true
                            cmd = Dict{Int,Int}(motors[n]["channel"] => a for (n, a) in sol)
                            cmd[motors[5]["channel"]] = ik_sliders["roll"].angle
                            cmd[motors[6]["channel"]] = claw_closed ? motors[6]["max"] : motors[6]["min"]
                            last_valid_ik_commands = cmd
                            local_commands = cmd
                        else
                            ik_reachable = false
                            local_commands = last_valid_ik_commands  # hold last good pose
                        end
                        warn_text = ik_reachable ? "" : "Target unreachable - holding last valid pose."
                    end
                elseif mode == "fleet"
                    warn_text = isempty(fleet_error) ?
                        "Open http://$fleet_lan_ip:$(args[:fleet_port]) in a browser to control" *
                        (args[:no_register] ? "" : "  -  heartbeating to RIFT at $(args[:rift_host]):$(args[:rift_port])") :
                        fleet_error
                end

                # Merge this mode's input into the shared angles, then always send/record the
                # shared state (so web-page and RIFT changes reach the arm in any mode).
                if local_commands !== nothing
                    local_by_motor = Dict{Int,Int}(channel_to_motor[ch] => a for (ch, a) in local_commands if haskey(channel_to_motor, ch))
                    if !adopted
                        if remote.synced  # connected: take the hub's state as-is, don't move the arm
                            empty!(prev_local)
                            merge!(prev_local, local_by_motor)
                            adopted = true
                        end
                    else
                        changed_now = merge_local!(local_by_motor, prev_local, fleet_state)
                        remote !== nothing && !isempty(changed_now) && queue_remote!(remote, changed_now)
                    end
                    mode == "slider" && follow_sliders!(slider_mode_sliders, motor_numbers, fleet_state, prev_local)
                end
                commands = lock(fleet_state.lock) do
                    Dict{Int,Int}(motors[n]["channel"] => fleet_state.angles[n] for n in motor_numbers)
                end

                last_sent = send_commands!(sp, commands, last_sent)
                if recording
                    push!(record_steps, MacroStep(time() - record_start, commands))
                end
            end

            if remote !== nothing
                status = "Remote arm $(args[:connect]): " * (remote.connected ? "connected" : "UNREACHABLE")
            end

            # ---- draw ----
            SDL_SetRenderDrawColor(renderer, BG_COLOR..., 255)
            SDL_RenderClear(renderer)

            draw_text!(renderer, font, "Arm Controller", 20, 12, TEXT_COLOR)
            draw_text!(renderer, small_font, status, 20, 38, STATUS_COLOR)

            for (name, rect) in mode_rects
                enabled = name != "joystick" || joystick_available
                draw_button!(renderer, font, rect, mode_labels[name], mx, my;
                             active=(mode == name), color=(enabled ? nothing : (50, 50, 50)), enabled=enabled)
            end

            record_label = recording ? "Recording... $(round(time() - record_start; digits=1))s" : "Record"
            draw_button!(renderer, font, record_rect, record_label, mx, my; color=(recording ? BUTTON_RECORD_COLOR : nothing))
            draw_button!(renderer, font, play_rect, playing ? "Stop" : "Play", mx, my; active=playing)

            if isempty(macros)
                draw_text!(renderer, small_font, "No macros recorded yet.", 30, MACRO_LIST_Y, STATUS_COLOR)
            else
                for i in 1:min(length(macros), MACRO_LIST_MAX)
                    row = macro_row_rect(i - 1)
                    i == selected_macro_index && fill_rect!(renderer, row, MACRO_SELECTED_COLOR)
                    name = splitext(basename(macros[i]))[1]
                    draw_text!(renderer, small_font, "$i. $name", row[1] + 4, row[2], TEXT_COLOR)
                end
            end

            if mode == "slider"
                for s in slider_mode_sliders
                    draw_slider!(renderer, font, s)
                end
            elseif mode == "ik"
                if !isempty(warn_text)
                    draw_text!(renderer, small_font, warn_text, 20, MARGIN_TOP - 20, WARN_COLOR)
                end
                if geometry_ready(geometry)
                    for key in ("x", "y", "z", "pitch", "roll")
                        draw_slider!(renderer, font, ik_sliders[key])
                    end
                    draw_button!(renderer, small_font, elbow_rect, elbow_down ? "Elbow: Down" : "Elbow: Up", mx, my)
                    draw_button!(renderer, small_font, claw_rect, claw_closed ? "Claw: Closed" : "Claw: Open", mx, my)
                end
            elseif mode == "joystick"
                if !isempty(warn_text)
                    draw_text!(renderer, small_font, warn_text, 20, MARGIN_TOP - 20, WARN_COLOR)
                elseif !isempty(last_sent)
                    channel_to_motor = Dict(m["channel"] => n for (n, m) in motors)
                    y = MARGIN_TOP
                    for (ch, ang) in sort(collect(last_sent))
                        n = get(channel_to_motor, ch, "?")
                        draw_text!(renderer, font, "Motor $n (ch $ch): $ang", 20, y, TEXT_COLOR)
                        y += 28
                    end
                end
            elseif mode == "fleet"
                draw_text!(renderer, small_font, warn_text, 20, MARGIN_TOP - 20, isempty(fleet_error) ? STATUS_COLOR : WARN_COLOR)
                y = MARGIN_TOP
                for n in sort(collect(keys(motors)))
                    ang = lock(() -> fleet_state.angles[n], fleet_state.lock)
                    draw_text!(renderer, font, "Motor $n (ch $(motors[n]["channel"])): $ang", 20, y, TEXT_COLOR)
                    y += 28
                end
            end

            if playing
                draw_text!(renderer, small_font, "Playing... step $(play_index - 1)/$(length(play_steps))",
                           370, TRANSPORT_BUTTON_Y + 6, STATUS_COLOR)
            end

            SDL_RenderPresent(renderer)
            sleep(args[:rate] > 0 ? 1.0 / args[:rate] : 0.033)  # sleep (not SDL_Delay) so HTTP.jl's tasks get to run
        end
    finally
        remote !== nothing && stop_remote_arm!(remote)
        sp !== nothing && close(sp)
        js != C_NULL && SDL_JoystickClose(js)
        font != C_NULL && TTF_CloseFont(font)
        small_font != C_NULL && TTF_CloseFont(small_font)
        renderer != C_NULL && SDL_DestroyRenderer(renderer)
        window != C_NULL && SDL_DestroyWindow(window)
        TTF_Quit()
        SDL_Quit()
    end
end

main()
