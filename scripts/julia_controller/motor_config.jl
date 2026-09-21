# motor_config.jl - Shared motor configuration, loaded from config.json at
# the repo root. Julia counterpart of scripts/motor_config.py - every
# motor-driving script here should call load_motor_config() instead of
# hardcoding servo channels/ranges, so config.json stays the single source
# of truth (shared with controller.py and the C++ controller).

import JSON3

const CONFIG_PATH = normpath(joinpath(@__DIR__, "..", "..", "config.json"))

const DEFAULT_MOTORS = Dict(
    1 => Dict("channel" => 0, "min" => 0, "max" => 270, "rest" => 135, "invert" => false, "kinematicSign" => 1),
    2 => Dict("channel" => 1, "min" => 0, "max" => 270, "rest" => 135, "invert" => false, "kinematicSign" => 1),
    3 => Dict("channel" => 2, "min" => 0, "max" => 270, "rest" => 135, "invert" => false, "kinematicSign" => 1),
    4 => Dict("channel" => 3, "min" => 0, "max" => 270, "rest" => 135, "invert" => false, "kinematicSign" => 1),
    5 => Dict("channel" => 4, "min" => 0, "max" => 270, "rest" => 135, "invert" => false, "kinematicSign" => 1),
    6 => Dict("channel" => 5, "min" => 0, "max" => 270, "rest" => 135, "invert" => false, "kinematicSign" => 1),
)

const DEFAULT_GEOMETRY = Dict(
    "units" => "mm",
    "baseHeight" => 0.0,
    "upperArmLength" => 0.0,
    "forearmLength" => 0.0,
    "wristLength" => 0.0,
)

function _read_config()
    isfile(CONFIG_PATH) || return nothing
    try
        return JSON3.read(read(CONFIG_PATH, String), Dict{String,Any})
    catch e
        println("Warning: could not read $(basename(CONFIG_PATH)) ($e), using defaults.")
        return nothing
    end
end

"""
    load_motor_config() -> Dict{Int,Dict{String,Any}}

Returns motor => {"channel","min","max","rest","invert","kinematicSign"},
merging config.json's "motors" section over DEFAULT_MOTORS.
"""
function load_motor_config()
    motors = Dict(n => copy(settings) for (n, settings) in DEFAULT_MOTORS)

    data = _read_config()
    data === nothing && return motors
    overrides_by_motor = get(data, "motors", Dict{String,Any}())

    for (key, overrides) in overrides_by_motor
        n = tryparse(Int, key)
        n === nothing && continue
        haskey(motors, n) || (motors[n] = copy(get(DEFAULT_MOTORS, n, DEFAULT_MOTORS[1])))
        for (k, v) in overrides
            motors[n][k] = v
        end
    end

    return motors
end

"""
    load_geometry() -> Dict{String,Any}

Returns the arm's link-length geometry (mm), merging config.json's
"geometry" section over DEFAULT_GEOMETRY.
"""
function load_geometry()
    geometry = copy(DEFAULT_GEOMETRY)

    data = _read_config()
    data === nothing && return geometry
    for (k, v) in get(data, "geometry", Dict{String,Any}())
        geometry[k] = v
    end

    return geometry
end

geometry_ready(geometry) = get(geometry, "upperArmLength", 0) != 0 && get(geometry, "forearmLength", 0) != 0
