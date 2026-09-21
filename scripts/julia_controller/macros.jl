# macros.jl - Record/replay motor-pose macros, saved as JSON. Julia
# counterpart of controller.py's macro helpers - reads/writes the same
# scripts/macros/*.json files as the Python and C++ controllers.

import JSON3
using Dates

const MACROS_DIR = normpath(joinpath(@__DIR__, "..", "macros"))

struct MacroStep
    t::Float64
    commands::Dict{Int,Int}   # channel -> angle
end

function list_macros()
    isdir(MACROS_DIR) || return String[]
    files = [f for f in readdir(MACROS_DIR; join=true) if endswith(f, ".json")]
    return sort(files; rev=true)
end

function save_macro(steps::Vector{MacroStep})
    mkpath(MACROS_DIR)
    path = joinpath(MACROS_DIR, "macro_$(Dates.format(now(), "yyyymmdd_HHMMSS")).json")
    payload = Dict(
        "created" => Dates.format(now(), "yyyy-mm-dd HH:MM:SS"),
        "steps" => [
            Dict("t" => s.t, "commands" => Dict(string(ch) => ang for (ch, ang) in s.commands))
            for s in steps
        ],
    )
    open(path, "w") do io
        JSON3.write(io, payload)
    end
    return path
end

function load_macro(path)
    data = JSON3.read(read(path, String), Dict{String,Any})
    steps = MacroStep[]
    for step in get(data, "steps", [])
        t = Float64(step["t"])
        commands = Dict{Int,Int}(parse(Int, ch) => round(Int, ang) for (ch, ang) in step["commands"])
        push!(steps, MacroStep(t, commands))
    end
    return steps
end
