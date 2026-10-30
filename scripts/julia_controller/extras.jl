# extras.jl - what controller.py has beyond driving her: her VOICE (arm_voice.ps1), her arm drawn from
# her geometry and joint maths, and the fleet's WiFi ladder (fleet_ladder.py, with --ladder).

const ARM_PANEL_W = 300
const VOICE_COOLDOWN_S = 8.0   # kit.Voice's: an event at most this often
const SCRIPTS_DIR = normpath(joinpath(@__DIR__, ".."))

mutable struct ArmVoice
    on::Bool
    last::Dict{String,Float64}
    seen::Union{Nothing,Tuple{String,Bool,Bool,Bool}}
end
ArmVoice() = ArmVoice(true, Dict{String,Float64}(), nothing)

function say!(v::ArmVoice, event::AbstractString)
    (!v.on || time() - get(v.last, event, -Inf) < VOICE_COOLDOWN_S) && return
    v.last[event] = time()
    script = joinpath(SCRIPTS_DIR, "arm_voice.ps1")
    try
        run(pipeline(`powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File $script $event`;
                     stdout=devnull, stderr=devnull); wait=false)
    catch
    end
end

# Once a frame: says what changed, as controller.py's main loop does.
function watch!(v::ArmVoice, mode, recording, playing, claw)
    was, v.seen = v.seen, (mode, recording, playing, claw)
    if was === nothing
        say!(v, "connect")
        return
    end
    was[1] != mode && say!(v, "mode_$mode")
    was[2] != recording && say!(v, recording ? "record_on" : "record_off")
    was[3] != playing && say!(v, playing ? "play" : "stop")
    was[4] != claw && say!(v, claw ? "claw_close" : "claw_open")
end

# The fleet's WiFi ladder while she runs (--ladder or FLEET_LADDER=1), as ARMCTL.
function start_ladder(asked)
    (asked || get(ENV, "FLEET_LADDER", "") == "1") || return nothing
    script = joinpath(SCRIPTS_DIR, "fleet_ladder.py")
    py = Sys.iswindows() ? "python" : "python3"
    try
        return run(`$py $script ARMCTL --run`; wait=false)
    catch
        return nothing
    end
end

function draw_line!(renderer, x1, y1, x2, y2, color; width=1)
    SDL_SetRenderDrawColor(renderer, color[1], color[2], color[3], 255)
    for o in (1:width) .- (width + 1) ÷ 2   # a thick line: several, side by side
        dx, dy = abs(x2 - x1) > abs(y2 - y1) ? (0, o) : (o, 0)
        SDL_RenderDrawLine(renderer, round(Int, x1) + dx, round(Int, y1) + dy, round(Int, x2) + dx, round(Int, y2) + dy)
    end
end

# clip: (x, y, w, h), only the part of the ring inside it
function draw_ring!(renderer, cx, cy, radius, color; clip=nothing)
    n = 90
    for i in 1:n
        a, b = 2π * (i - 1) / n, 2π * i / n
        x1, y1, x2, y2 = cx + radius * cos(a), cy + radius * sin(a), cx + radius * cos(b), cy + radius * sin(b)
        clip !== nothing && !(point_in(x1, y1, clip) && point_in(x2, y2, clip)) && continue
        draw_line!(renderer, x1, y1, x2, y2, color)
    end
end

# Her arm, as controller.py's draw_arm(): from the side, and from above (the base turning).
function draw_arm!(renderer, font, motors, geometry, angles, x0)
    panel = (x0 + 8, 56, ARM_PANEL_W - 16, 560)
    fill_rect!(renderer, panel, SCHEME["panel"])
    track, knob, accent = SCHEME["track"], SCHEME["button_hover"], SCHEME["accent"]
    px, py, w = panel[1], panel[2], panel[3]
    draw_text!(renderer, font, "from the side", px + 10, py + 8, STATUS_COLOR)

    joint(n) = deg2rad(raw_to_deg(motors, n, get(angles, n, motors[n]["rest"])))
    l1, l2, l3, h0 = geometry["upperArmLength"], geometry["forearmLength"], geometry["wristLength"], geometry["baseHeight"]
    reach = l1 + l2 + l3
    reach <= 0 && (reach = 300.0)
    s = min((w - 60) / reach, 230 / (reach + h0))
    X(r) = px + 30 + r * s
    Z(z) = py + 270 - z * s
    draw_line!(renderer, px + 10, py + 270, px + w - 10, py + 270, track)
    draw_ring!(renderer, X(0), Z(h0), reach * s, track; clip=(px, py + 24, w, 276))

    a1 = joint(2); a2 = a1 + joint(3); a3 = a2 + joint(4)
    r, z = 0.0, Float64(h0)
    for (len, a) in ((l1, a1), (l2, a2), (l3, a3))
        r2, z2 = r + len * cos(a), z + len * sin(a)
        draw_line!(renderer, X(r), Z(z), X(r2), Z(z2), knob; width=5)
        draw_circle_filled!(renderer, round(Int, X(r2)), round(Int, Z(z2)), 6, accent)
        r, z = r2, z2
    end
    open = haskey(angles, 6) && angles[6] < motors[6]["rest"] ? 0.25 : 0.5
    for sgn in (-1, 1)
        draw_line!(renderer, X(r), Z(z), X(r) + 14cos(a3 + sgn * open), Z(z) - 14sin(a3 + sgn * open), accent; width=3)
    end
    draw_text!(renderer, font, "tip  r $(round(Int, r))  z $(round(Int, z)) mm", px + 10, py + 280, TEXT_COLOR)

    base = joint(1)
    cx, cy, rr = px + w / 2, py + 440, r * 100 / reach
    draw_text!(renderer, font, "from above", px + 10, py + 315, STATUS_COLOR)
    draw_ring!(renderer, cx, cy, 100, track)
    tx, ty = cx + rr * sin(base), cy - rr * cos(base)
    draw_line!(renderer, cx, cy, tx, ty, knob; width=5)
    draw_circle_filled!(renderer, round(Int, cx), round(Int, cy), 8, accent)
    draw_circle_filled!(renderer, round(Int, tx), round(Int, ty), 5, accent)
    draw_text!(renderer, font, "base $(round(Int, rad2deg(base))) deg", px + 10, py + 540, TEXT_COLOR)
end
